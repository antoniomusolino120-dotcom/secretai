"""Tenant-scoped call provisioning and the Asterisk AudioSocket voice service."""
import asyncio
import contextlib
import io
import json
import math
import os
import re
import struct
import sys
import time
import uuid
import wave
from array import array
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.internal import service_auth
from app.auth import audit

class VoiceRoute(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transfer_channel: str = Field(default='', pattern=r'^(?:PJSIP/[A-Za-z0-9_+@.:-]{1,120})?$')
    greeting: str = Field(default='Sono SecretAI, la segretaria virtuale. Come posso aiutarti?', min_length=1, max_length=500)
    enabled: bool = False

class CallStart(BaseModel):
    route_id: str = Field(min_length=20, max_length=80)


def install(database, current_user, require_org):
    router = APIRouter(tags=['voice'])
    @router.get('/api/voice/routes')
    def routes(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database() as db:
            return [dict(r) for r in db.execute('SELECT * FROM voice_routes WHERE organization_id=?',(organization_id,))]
    @router.post('/api/voice/routes')
    def create_route(organization_id: int, data: VoiceRoute, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        rid = uuid.uuid4().hex
        with database(write=True, organization_id=organization_id) as db:
            db.execute('INSERT INTO voice_routes(id,organization_id,name,transfer_channel,greeting,enabled) VALUES (?,?,?,?,?,?)',(rid,organization_id,data.name,data.transfer_channel,data.greeting,int(data.enabled)))
            audit(db,'voice.route_created',user_id,organization_id,rid)
        return {'id':rid,**data.model_dump()}
    @router.put('/api/voice/routes/{route_id}')
    def update_route(route_id: str, organization_id: int, data: VoiceRoute, user_id: int = Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database(write=True, organization_id=organization_id) as db:
            if db.execute('UPDATE voice_routes SET name=?,transfer_channel=?,greeting=?,enabled=? WHERE id=? AND organization_id=?',(data.name,data.transfer_channel,data.greeting,int(data.enabled),route_id,organization_id)).rowcount != 1:
                raise HTTPException(404,'Linea inesistente')
        return {'ok':True}
    @router.get('/api/voice/calls')
    def calls(organization_id: int,user_id: int=Depends(current_user)):
        require_org(user_id,organization_id)
        with database() as db:
            return [dict(r) for r in db.execute('SELECT * FROM voice_calls WHERE organization_id=? ORDER BY created_at DESC LIMIT 100',(organization_id,))]
    @router.post('/internal/voice/calls', dependencies=[Depends(service_auth)])
    def call_start(data: CallStart):
        cid = str(uuid.uuid4()); now = int(time.time())
        with database(write=True) as db:
            route = db.execute('SELECT * FROM voice_routes WHERE id=? AND enabled=1',(data.route_id,)).fetchone()
            if not route: raise HTTPException(404,'Route unavailable')
            org_id=route['organization_id']; db.lock_org(org_id)
            if not db.execute('SELECT assistant_enabled FROM organizations WHERE id=?',(org_id,)).fetchone()['assistant_enabled']:
                raise HTTPException(409,'Segretaria disattivata: usare la linea operatore')
            # Caller ID is not an authenticated customer identity. A fresh voice
            # conversation can book but cannot inspect or mutate prior customers.
            conv = db.execute("INSERT INTO conversations(organization_id,channel,external_id,updated_at) VALUES (?,'voice',?,?)",(org_id,cid,now)).lastrowid
            db.execute('INSERT INTO voice_calls(id,organization_id,route_id,conversation_id,created_at) VALUES (?,?,?,?,?)',(cid,org_id,data.route_id,conv,now))
        return {'call_id':cid}
    @router.get('/internal/voice/calls/{call_id}', dependencies=[Depends(service_auth)])
    def call_state(call_id: str):
        with database() as db:
            row=db.execute('SELECT c.status,r.transfer_channel FROM voice_calls c JOIN voice_routes r ON r.id=c.route_id WHERE c.id=?',(call_id,)).fetchone()
        if not row: raise HTTPException(404,'Call unavailable')
        return {'status':row['status'],'transfer_channel':row['transfer_channel'] if row['status'] in {'created','human','failed','quota'} else ''}
    return router


def packet(kind, payload=b''):
    if len(payload)>65535: raise ValueError('Frame too large')
    return bytes([kind])+len(payload).to_bytes(2,'big')+payload

async def read_packet(reader):
    header=await reader.readexactly(3); size=int.from_bytes(header[1:],'big')
    return header[0], await reader.readexactly(size)

class SpeechEngines:
    """Local Whisper + Piper; no cloud credential or fake production fallback."""
    def __init__(self):
        from concurrent.futures import ThreadPoolExecutor
        self.model=None;self.tts=None
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='secretai-stt')
        self.tts_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='secretai-tts')
    async def transcribe(self, pcm):
        def run():
            from faster_whisper import WhisperModel
            if self.model is None:
                self.model=WhisperModel(os.getenv('WHISPER_MODEL','small'),device='cpu',compute_type='int8',download_root=os.getenv('WHISPER_DOWNLOAD_ROOT'))
            import numpy as np
            samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
            # AudioSocket input is 8kHz. Whisper consumes 16kHz mono floats.
            samples=np.interp(np.arange(len(samples)*2)/2,np.arange(len(samples)),samples).astype(np.float32)
            segments,_=self.model.transcribe(samples,language='it',beam_size=3,vad_filter=True)
            return ' '.join(s.text for s in segments).strip()
        return await asyncio.get_running_loop().run_in_executor(self.executor,run)
    async def synthesize(self,text):
        def run():
            from piper.voice import PiperVoice
            import numpy as np
            model=os.environ.get('PIPER_MODEL','')
            if not model or not Path(model).is_file(): raise RuntimeError('Piper model unavailable')
            if self.tts is None:self.tts=PiperVoice.load(model)
            raw=b''.join(chunk.audio_int16_bytes for chunk in self.tts.synthesize(text))
            sample_rate=self.tts.config.sample_rate
            values=np.frombuffer(raw,dtype='<i2')
            if sample_rate!=8000 and len(values):
                values=np.interp(np.arange(int(len(values)*8000/sample_rate))*sample_rate/8000,np.arange(len(values)),values).astype('<i2')
            return values.tobytes()
        return await asyncio.get_running_loop().run_in_executor(self.tts_executor,run)


class VoiceService:
    def __init__(self,database,engines=None,responder=None):
        self.database=database; self.engines=engines or SpeechEngines()
        if responder is None:
            from app.assistant import respond
            responder=respond
        self.responder=responder
    async def handle(self,reader,writer):
        cid=None; output=None; turn=None; timer=None; frames=0; charged=0; utterance=bytearray(); silence=0; speech=0; counter=0
        async def play(text):
            pcm=await self.engines.synthesize(text)
            for offset in range(0,len(pcm),320):
                writer.write(packet(0x10,pcm[offset:offset+320])); await writer.drain(); await asyncio.sleep(.02)
        def status(value):
            with self.database(write=True) as db:
                db.execute('UPDATE voice_calls SET status=? WHERE id=?',(value,cid))
        def spawn(coro):
            task=asyncio.create_task(coro)
            def finished(t):
                if not t.cancelled() and t.exception() is not None:
                    if cid: status('failed')
                    writer.close()
            task.add_done_callback(finished)
            return task
        async def handle_turn(audio,number):
            nonlocal output
            text=await self.engines.transcribe(audio)
            if not text: return
            with self.database(write=True,organization_id=call['organization_id']) as db:
                db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,external_id) VALUES (?,?,'inbound',?,?,?)",(call['organization_id'],call['conversation_id'],text[:4000],int(time.time()),f'voice:{cid}:in:{number}'))
            result=await self.responder(self.database,call['organization_id'],text,conversation_id=call['conversation_id'])
            with self.database(write=True,organization_id=call['organization_id']) as db:
                db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,delivery_status,external_id) VALUES (?,?,'outbound',?,?,'sent',?)",(call['organization_id'],call['conversation_id'],result['reply'][:4000],int(time.time()),f'voice:{cid}:out:{number}'))
            output=spawn(play(result['reply'][:800]))
            await output
            if result['mode'] in {'human','offline'}:
                status('human'); writer.write(packet(0)); await writer.drain(); writer.close()
        try:
            kind,data=await asyncio.wait_for(read_packet(reader),timeout=10)
            if kind!=1 or len(data)!=16: raise ValueError('UUID frame required')
            cid=str(uuid.UUID(bytes=data))
            with self.database(write=True) as db:
                call=db.execute('SELECT c.*,r.greeting FROM voice_calls c JOIN voice_routes r ON r.id=c.route_id WHERE c.id=? AND c.status=\'created\' AND c.created_at>?',(cid,int(time.time())-60)).fetchone()
                if not call: raise ValueError('Unknown or expired call')
                if db.execute("UPDATE voice_calls SET status='active' WHERE id=? AND status='created'",(cid,)).rowcount!=1: raise ValueError('Call already attached')
            async def deadline():
                await asyncio.sleep(int(os.getenv('VOICE_MAX_SECONDS','900'))); status('human'); writer.close()
            timer=asyncio.create_task(deadline())
            output=spawn(play(call['greeting']))
            while not writer.is_closing():
                kind,data=await asyncio.wait_for(read_packet(reader),timeout=30)
                if kind==0: break
                if kind==3 and data==b'0':
                    status('human'); break
                if kind!=0x10: continue
                if len(data)%2 or len(data)>3200: raise ValueError('Invalid PCM frame')
                frames+=len(data)//2
                seconds=math.ceil(frames/8000)
                if seconds>charged:
                    from app.billing import consume
                    try: consume(self.database,call['organization_id'],'voice_seconds',seconds-charged,f'voice:{cid}:seconds:{seconds}')
                    except HTTPException:
                        status('quota'); break
                    charged=seconds
                values=struct.unpack('<'+'h'*(len(data)//2),data)
                rms=math.sqrt(sum(x*x for x in values)/max(1,len(values)))
                duration=len(data)//16
                if rms>int(os.getenv('VOICE_VAD_RMS','450')):
                    speech+=duration; silence=0; utterance.extend(data)
                    if speech>=120:
                        if output and not output.done(): output.cancel()
                        if turn and not turn.done():
                            turn.cancel()
                            with contextlib.suppress(asyncio.CancelledError): await turn
                elif utterance:
                    silence+=duration; utterance.extend(data)
                if utterance and (silence>=600 or len(utterance)>=160000):
                    if speech>=160:
                        counter+=1; turn=spawn(handle_turn(bytes(utterance),counter))
                    utterance.clear(); silence=0; speech=0
                if turn and turn.done() and not turn.cancelled(): turn.result()
                if output and output.done() and not output.cancelled(): output.result()
        except (asyncio.IncompleteReadError,ConnectionError): pass
        except asyncio.CancelledError: raise
        except Exception:
            if cid: status('failed')
        finally:
            for task in (output,turn,timer):
                if task and not task.done(): task.cancel()
            for task in (output,turn,timer):
                if task:
                    with contextlib.suppress(asyncio.CancelledError,Exception): await task
            if cid:
                with self.database(write=True) as db:
                    db.execute("UPDATE voice_calls SET ended_at=?,seconds=?,status=CASE WHEN status='active' THEN 'completed' ELSE status END WHERE id=?",(int(time.time()),charged,cid))
            writer.close()
            with contextlib.suppress(Exception): await writer.wait_closed()

async def main():
    from app.db import build_engine,initialize,make_database
    engine=build_engine(); initialize(engine)
    database=make_database(engine)
    engines=SpeechEngines()
    await engines.synthesize('La segretaria è pronta.')
    await engines.transcribe(b'\0\0'*8000)
    service=VoiceService(database,engines)
    async def pulse():
        from app.operations import heartbeat
        while True:
            heartbeat(database,'voice');await asyncio.sleep(30)
    asyncio.create_task(pulse())
    server=await asyncio.start_server(service.handle,os.getenv('VOICE_BIND','0.0.0.0'),int(os.getenv('VOICE_PORT','9019')))
    async with server: await server.serve_forever()

if __name__=='__main__': asyncio.run(main())
