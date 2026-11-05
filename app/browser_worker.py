"""Isolated Playwright worker: bounded actions, pinned allowed hosts, encrypted state."""
import asyncio
import base64
import contextlib
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from app.internal import service_auth
from app.secrets import encrypt,decrypt


def validate_origin(value):
    p=urlsplit(value)
    origin=f'{p.scheme}://{p.netloc}'
    allowed={v.strip().rstrip('/') for v in os.getenv('BROWSER_ALLOWED_ORIGINS','').split(',') if v.strip()}
    test=os.getenv('SECRET_AI_ENV')!='production' and os.getenv('BROWSER_ALLOW_LOCAL_TEST')=='1'
    if p.username or p.password or p.fragment or p.query or p.path not in {'','/'} or origin not in allowed or (p.scheme!='https' and not test):
        raise HTTPException(422,'Dominio non autorizzato dal gestore')
    return origin


def resolver_rules(origins):
    rules=[]
    test=os.getenv('SECRET_AI_ENV')!='production' and os.getenv('BROWSER_ALLOW_LOCAL_TEST')=='1'
    for origin in origins:
        host=urlsplit(origin).hostname
        addresses={r[4][0] for r in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)}
        if not addresses or (not test and any(not ipaddress.ip_address(a).is_global for a in addresses)):
            raise HTTPException(422,'Destinazione di rete non consentita')
        address=next((a for a in addresses if ':' not in a),sorted(addresses)[0])
        rules.append('MAP '+host+' '+('['+address+']' if ':' in address else address))
    return ','.join(rules)+',EXCLUDE localhost'


def interpolate(value,variables):
    def replace(match):
        key=match.group(1)
        if key not in variables: raise ValueError('Missing parameter')
        return variables[key]
    return re.sub(r'\$\{([A-Za-z0-9_]+)\}',replace,value)

SELECTOR_SCRIPT='''([x,y])=>{let e=document.elementFromPoint(x,y);if(!e)throw Error('No element');if(e.id)return '#'+CSS.escape(e.id);if(e.dataset.testid)return '[data-testid="'+CSS.escape(e.dataset.testid)+'"]';let path=[];while(e&&e.nodeType===1&&e!==document.body){let n=e.tagName.toLowerCase(),a=e.parentElement?Array.from(e.parentElement.children).filter(i=>i.tagName===e.tagName):[];path.unshift(n+(a.length>1?':nth-of-type('+(a.indexOf(e)+1)+')':''));e=e.parentElement}return 'body>'+path.join('>')}'''

class Runtime:
    def __init__(self,database): self.database=database;self.sessions={};self.playwright=None;self.lock=asyncio.Lock()
    async def context(self,origin,state=None):
        from playwright.async_api import async_playwright
        origins={origin,*[v.strip().rstrip('/') for v in os.getenv('BROWSER_AUTH_ORIGINS','').split(',') if v.strip()]}
        rules=resolver_rules(origins)
        async with self.lock:
            if not self.playwright: self.playwright=await async_playwright().start()
        browser=await self.playwright.chromium.launch(headless=True,args=['--host-resolver-rules='+rules,'--disable-quic'])
        context=await browser.new_context(viewport={'width':1280,'height':900},storage_state=state,service_workers='block',accept_downloads=False)
        async def guard(route):
            p=urlsplit(route.request.url)
            if f'{p.scheme}://{p.netloc}' not in origins: await route.abort('blockedbyclient')
            else: await route.continue_()
        await context.route('**/*',guard)
        if hasattr(context,'route_web_socket'):
            await context.route_web_socket('**/*',lambda ws: ws.close())
        context.set_default_timeout(10000)
        return browser,context
    async def close(self,sid):
        session=self.sessions.pop(sid,None)
        if session: await session['browser'].close()
    async def get(self,sid,org):
        s=self.sessions.get(sid)
        if not s or s['org']!=org: raise HTTPException(404,'Sessione inesistente')
        if s['expires']<time.time():
            await self.close(sid);raise HTTPException(410,'Sessione scaduta')
        return s
    async def snapshot(self,s):
        return {'image':'data:image/png;base64,'+base64.b64encode(await s['page'].screenshot()).decode(),'url':s['page'].url,'steps':s['steps'],'recording':s['recording']}
    async def open(self,pid,org):
        for sid,s in list(self.sessions.items()):
            if s['expires']<time.time(): await self.close(sid)
        if len(self.sessions)>=int(os.getenv('BROWSER_MAX_SESSIONS','4')): raise HTTPException(429,'Troppe sessioni browser')
        with self.database() as db: p=db.execute('SELECT * FROM browser_procedures WHERE id=? AND organization_id=?',(pid,org)).fetchone()
        if not p: raise HTTPException(404,'Procedura inesistente')
        validate_origin(p['origin'])
        state=json.loads(decrypt(p['state_ciphertext'])) if p['state_ciphertext'] else None
        browser,context=await self.context(p['origin'],state)
        try:
            page=await context.new_page();await page.goto(p['origin'],wait_until='domcontentloaded')
        except BaseException:
            await browser.close();raise
        sid=secrets.token_urlsafe(32)
        self.sessions[sid]={'org':org,'pid':pid,'browser':browser,'context':context,'page':page,'steps':[],'recording':False,'origin':p['origin'],'expires':time.time()+1800,'lock':asyncio.Lock()}
        return {'id':sid,**await self.snapshot(self.sessions[sid])}
    async def act(self,s,action):
        async with s['lock']:
            page=s['page'];kind=action['action'];selector=action.get('selector','');value=action.get('value','')
            if not selector and action.get('x') is not None:
                selector=await page.evaluate(SELECTOR_SCRIPT,[action['x'],action['y']])
            if kind=='record':
                from urllib.parse import parse_qs
                p=urlsplit(page.url)
                if f'{p.scheme}://{p.netloc}'!=s['origin'] or set(parse_qs(p.query)) & {'code','token','access_token','session','sessionid'}:
                    raise HTTPException(422,'Apri la pagina del gestionale dopo aver completato l’accesso')
                s['recording']=True;s['steps']=[{'action':'goto','selector':'','value':page.url}]
                return await self.snapshot(s)
            if kind=='inspect': return {**await self.snapshot(s),'selector':selector}
            if kind=='goto':
                target=urlsplit(value)
                if f'{target.scheme}://{target.netloc}'!=urlsplit(page.url).scheme+'://'+urlsplit(page.url).netloc: raise HTTPException(422,'Navigazione esterna non registrabile')
                await page.goto(value,wait_until='domcontentloaded')
            elif kind=='click': await page.locator(selector).click()
            elif kind in {'fill','select'}:
                parameter=action.get('parameter','')
                # Demonstrated input is always parameterized; no password/PII is
                # persisted in a recorded procedure or audit payload.
                if s['recording'] and not re.fullmatch('[A-Za-z0-9_]{1,80}',parameter): raise HTTPException(422,'Assegna un nome al parametro del campo')
                if kind=='fill': await page.locator(selector).fill(value)
                else: await page.locator(selector).select_option(value)
                value='${'+parameter+'}'
            elif kind=='capture':
                if not re.fullmatch('[A-Za-z0-9_]{1,80}',action.get('parameter','')): raise HTTPException(422,'Assegna un nome al dato da leggere')
                value=action['parameter']
                await page.locator(selector).inner_text()
            elif kind=='assert_text':
                from playwright.async_api import expect
                await expect(page.locator(selector)).to_contain_text(value,timeout=10000)
            elif kind=='assert_url':
                if value not in page.url: raise HTTPException(422,'Verifica URL fallita')
            else: raise HTTPException(422,'Azione non supportata')
            if s['recording']: s['steps'].append({'action':kind,'selector':selector,'value':value})
            return await self.snapshot(s)
    async def save(self,s):
        async with s['lock']:
            if not s['steps'] or not s['steps'][-1]['action'].startswith('assert_'): raise HTTPException(422,'Aggiungi una verifica finale prima di salvare')
            state=await s['context'].storage_state()
            with self.database(write=True,organization_id=s['org']) as db:
                db.execute('UPDATE browser_procedures SET state_ciphertext=?,steps_json=?,version=version+1,approved=0,updated_at=? WHERE id=? AND organization_id=?',(encrypt(json.dumps(state)),json.dumps(s['steps']),int(time.time()),s['pid'],s['org']))
        return {'saved':True,'approval_required':True}
    async def execute(self,rid,org):
        with self.database(write=True,organization_id=org) as db:
            run=db.execute('SELECT * FROM browser_runs WHERE id=? AND organization_id=?',(rid,org)).fetchone()
            if not run: raise HTTPException(404,'Esecuzione inesistente')
            if run['status']!='pending': return {'status':run['status']}
            p=db.execute('SELECT * FROM browser_procedures WHERE id=? AND organization_id=?',(run['procedure_id'],org)).fetchone()
            if not p or not p['approved'] or p['version']!=run['version']: raise HTTPException(409,'Versione non approvata o modificata')
            db.execute("UPDATE browser_runs SET status='running' WHERE id=?",(rid,))
        browser=None;status='attention';result={'reason':'Execution interrupted; verify external outcome before retrying'}
        try:
            validate_origin(p['origin']);variables=json.loads(decrypt(run['variables_ciphertext']))
            browser,context=await self.context(p['origin'],json.loads(decrypt(p['state_ciphertext'])) if p['state_ciphertext'] else None)
            page=await context.new_page();await page.goto(p['origin'],wait_until='domcontentloaded')
            steps=json.loads(p['steps_json']);captures={}
            for number,step in enumerate(steps):
                # Commit intent before each external effect. Crashed runs are
                # marked attention, never automatically replayed by the outbox.
                with self.database(write=True,organization_id=org) as db: db.execute('UPDATE browser_runs SET step=? WHERE id=? AND organization_id=?',(number,rid,org))
                if await page.locator('iframe[src*="captcha"],input[autocomplete="one-time-code"]').count(): raise ValueError('Human verification required')
                kind=step['action'];value=interpolate(step['value'],variables);locator=page.locator(step['selector']) if step['selector'] else None
                if kind=='goto': await page.goto(value,wait_until='domcontentloaded')
                elif kind=='click': await locator.click()
                elif kind=='fill': await locator.fill(value)
                elif kind=='select': await locator.select_option(value)
                elif kind=='capture': captures[value]=(await locator.inner_text())[:500]
                elif kind=='assert_text':
                    from playwright.async_api import expect
                    await expect(locator).to_contain_text(value,timeout=10000)
                elif kind=='assert_url':
                    if value not in page.url: raise ValueError('Result URL mismatch')
                else: raise ValueError('Unsupported action')
            if not steps or not steps[-1]['action'].startswith('assert_'): raise ValueError('Verification required')
            status='verified';result={'verified':True,'steps':len(steps),'captures':captures}
        except asyncio.CancelledError: raise
        except Exception: pass
        finally:
            if browser: await browser.close()
            with self.database(write=True,organization_id=org) as db:
                db.execute('UPDATE browser_runs SET status=?,result_json=?,variables_ciphertext=? WHERE id=? AND organization_id=?',(status,json.dumps(result),'',rid,org))
                if run['appointment_id']:
                    finish_appointment(self.database,org,run['appointment_id'],run['operation'],status,result,db=db)
        return {'status':status,**result}

def finish_appointment(database,org,aid,operation,status,result,db=None):
    from app.booking import enqueue
    with (database(write=True,organization_id=org) if db is None else contextlib.nullcontext(db)) as db:
        row=db.execute('SELECT * FROM appointments WHERE id=? AND organization_id=?',(aid,org)).fetchone()
        if not row:return
        if status!='verified':
            db.execute("UPDATE appointments SET sync_status='attention' WHERE id=? AND organization_id=?",(aid,org));return
        reference=result.get('captures',{}).get('booking_reference',row['external_reference'])
        db.execute('UPDATE appointments SET external_reference=? WHERE id=? AND organization_id=?',(reference,aid,org))
        google=db.execute('SELECT 1 FROM google_connections WHERE organization_id=?',(org,)).fetchone()
        if google:
            state='cancelling' if operation=='cancel' else 'pending_sync'
            db.execute("UPDATE appointments SET status=?,sync_status='pending' WHERE id=? AND organization_id=?",(state,aid,org))
            enqueue(db,org,'google_delete' if operation=='cancel' else 'google_upsert',{'appointment_id':aid},f'google:browser:{aid}:{operation}:{time.time_ns()}')
        else:
            db.execute("UPDATE appointments SET status=?,sync_status='local' WHERE id=? AND organization_id=?",('cancelled' if operation=='cancel' else 'confirmed',aid,org))
            db.execute('DELETE FROM appointment_holds WHERE organization_id=? AND appointment_id=?',(org,aid))


class SessionStart(BaseModel): procedure_id:str;organization_id:int
class Tenant(BaseModel): organization_id:int

@asynccontextmanager
async def lifespan(app):
    from app.db import build_engine,initialize,make_database
    engine=build_engine();initialize(engine);app.state.runtime=Runtime(make_database(engine))
    async def reap():
        while True:
            from app.operations import heartbeat
            heartbeat(app.state.runtime.database,'browser')
            await asyncio.sleep(30)
            for sid,s in list(app.state.runtime.sessions.items()):
                if s['expires']<time.time(): await app.state.runtime.close(sid)
    task=asyncio.create_task(reap())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError): await task
    for sid in list(app.state.runtime.sessions): await app.state.runtime.close(sid)
    if app.state.runtime.playwright: await app.state.runtime.playwright.stop()
    engine.dispose()

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None,dependencies=[Depends(service_auth)])
@app.post('/sessions')
async def start(data:SessionStart): return await app.state.runtime.open(data.procedure_id,data.organization_id)
@app.get('/sessions/{sid}')
async def snapshot(sid:str,organization_id:int): return await app.state.runtime.snapshot(await app.state.runtime.get(sid,organization_id))
@app.post('/sessions/{sid}/action')
async def act(sid:str,organization_id:int,action:dict): return await app.state.runtime.act(await app.state.runtime.get(sid,organization_id),action)
@app.post('/sessions/{sid}/save')
async def save(sid:str,organization_id:int): return await app.state.runtime.save(await app.state.runtime.get(sid,organization_id))
@app.delete('/sessions/{sid}')
async def close(sid:str,organization_id:int):
    await app.state.runtime.get(sid,organization_id);await app.state.runtime.close(sid);return {'ok':True}
@app.post('/runs/{rid}')
async def run(rid:str,data:Tenant): return await asyncio.wait_for(app.state.runtime.execute(rid,data.organization_id),timeout=90)
