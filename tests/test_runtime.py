import asyncio
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import uuid
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from app import assistant,google_reconcile
from app.booking import management_code,mutate_booking
from app.browser_worker import Runtime,resolver_rules
from app.jobs import run_once
from app.operations import schedule
from app.voice import VoiceService,packet,read_packet
from conftest import outsider


def encrypted(monkeypatch): monkeypatch.setenv('SECRET_AI_ENCRYPTION_KEY',Fernet.generate_key().decode())

def mock_http(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(*a,**{**kw,'transport':httpx.MockTransport(handler),'trust_env':False}))


def test_voice_private_provisioning_and_audio_barge_in_handoff(workspace,monkeypatch):
    c,main,org,service,_=workspace
    key='private-service-token-with-more-than-32-characters'
    monkeypatch.setenv('SECRET_AI_INTERNAL_TOKEN',key)
    with main.database(write=True) as db:db.execute('UPDATE organizations SET assistant_enabled=1 WHERE id=?',(org,))
    route=c.post(f'/api/voice/routes?organization_id={org}',json={'name':'Prova','enabled':True,'transfer_channel':'PJSIP/operator'}).json()['id']
    assert c.post('/internal/voice/calls',json={'route_id':route}).status_code==403
    cid=c.post('/internal/voice/calls',json={'route_id':route},headers={'Authorization':'Bearer '+key}).json()['call_id']
    class Engines:
        async def transcribe(self,pcm):return 'Vorrei un operatore'
        async def synthesize(self,text):return b'\0\0'*(160 if 'operatore' in text else 16000)
    async def responder(*a,**kw):return {'reply':'Ti passo un operatore','mode':'human'}
    async def exercise():
        service=VoiceService(main.database,Engines(),responder)
        server=await asyncio.start_server(service.handle,'127.0.0.1',0)
        reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
        writer.write(packet(1,uuid.UUID(cid).bytes));await writer.drain()
        # The greeting starts, then caller speech interrupts its two-second PCM.
        kind,data=await asyncio.wait_for(read_packet(reader),2);assert kind==0x10
        for _ in range(10): writer.write(packet(0x10,struct.pack('<160h',*([2000]*160))))
        for _ in range(31): writer.write(packet(0x10,b'\0\0'*160))
        await writer.drain();output_frames=1
        while True:
            kind,data=await asyncio.wait_for(read_packet(reader),3)
            if kind==0:break
            output_frames+=1
        assert output_frames<100,'Greeting was not interrupted'
        writer.close();await writer.wait_closed();server.close();await server.wait_closed();await asyncio.sleep(.1)
    asyncio.run(exercise())
    result=c.get('/internal/voice/calls/'+cid,headers={'Authorization':'Bearer '+key}).json()
    assert result=={'status':'human','transfer_channel':'PJSIP/operator'}
    with main.database() as db:
        call=db.execute('SELECT * FROM voice_calls WHERE id=?',(cid,)).fetchone()
        assert call['ended_at'] and call['seconds']>0
        assert len(db.execute('SELECT * FROM messages WHERE conversation_id=?',(call['conversation_id'],)).fetchall())==2


def test_voice_routes_and_browser_state_are_tenant_scoped(workspace,monkeypatch):
    c,main,org,_,_=workspace
    route=c.post(f'/api/voice/routes?organization_id={org}',json={'name':'Linea'}).json()['id']
    outsider(c)
    for endpoint in [f'voice/routes?organization_id={org}',f'voice/calls?organization_id={org}',f'browser/procedures?organization_id={org}',f'browser/runs?organization_id={org}',f'operations/health?organization_id={org}']:
        assert c.get('/api/'+endpoint).status_code==403
    assert c.put(f'/api/voice/routes/{route}?organization_id={org}',json={'name':'Forbidden'}).status_code==403


def test_customer_mutation_requires_identity_or_private_management_code(workspace,monkeypatch):
    c,main,org,sid,_=workspace;encrypted(monkeypatch)
    a=c.post('/api/appointments',json={'organization_id':org,'service_id':sid,'customer':'Customer','starts_at':'2027-10-01T10:00:00+02:00'}).json()
    cid=c.post('/api/conversations',json={'organization_id':org}).json()['id']
    args=assistant.ChangeProposal(appointment_id=a['id'],operation='cancel')
    with pytest.raises(HTTPException) as err:assistant.propose_change(main.database,org,args,cid,None)
    assert err.value.status_code==403
    args.management_code=management_code(org,a['id'])
    proposal=assistant.propose_change(main.database,org,args,cid,None)
    assert c.get(f'/api/appointments?organization_id={org}').json()[0]['status']=='confirmed'
    result=assistant.confirm(main.database,org,proposal['proposal_id'],conversation_id=cid)
    assert result['appointment']['status']=='cancelled'
    assert assistant.confirm(main.database,org,proposal['proposal_id'],conversation_id=cid)==result


def test_reschedule_holds_previous_slot_until_provider_verification(workspace):
    c,main,org,sid,_=workspace
    a=c.post('/api/appointments',json={'organization_id':org,'service_id':sid,'customer':'Customer','starts_at':'2027-10-01T10:00:00+02:00'}).json()
    with main.database(write=True) as db:
        db.execute("INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,'encrypted')",(org,))
        db.execute("UPDATE appointments SET sync_status='synced',external_event_id='event' WHERE id=?",(a['id'],))
    r=c.patch(f'/api/appointments/{a["id"]}?organization_id={org}',json={'starts_at':'2027-10-01T12:00:00+02:00'})
    assert r.status_code==200
    assert c.post('/api/appointments',json={'organization_id':org,'service_id':sid,'customer':'Other','starts_at':'2027-10-01T10:00:00+02:00'}).status_code==409


def test_google_incremental_sync_cancellation_and_invalidated_cursor(workspace,monkeypatch):
    c,main,org,sid,_=workspace;encrypted(monkeypatch)
    monkeypatch.setenv('GOOGLE_CLIENT_ID','id');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','secret');monkeypatch.setenv('GOOGLE_REDIRECT_URI','https://app.example/callback')
    from app.secrets import encrypt
    a=c.post('/api/appointments',json={'organization_id':org,'service_id':sid,'customer':'Customer','starts_at':'2027-10-01T10:00:00+02:00'}).json()
    with main.database(write=True) as db:
        db.execute('INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,?)',(org,encrypt('refresh')))
        db.execute("UPDATE appointments SET external_event_id='own-event',sync_status='synced' WHERE id=?",(a['id'],))
    steps=[]
    def handler(request):
        if request.url.path.endswith('/token'):return httpx.Response(200,json={'access_token':'access'})
        cursor=request.url.params.get('syncToken');steps.append(cursor)
        if cursor=='invalid':return httpx.Response(410,json={})
        if cursor=='first':return httpx.Response(200,json={'items':[{'id':'own-event','status':'cancelled'}],'nextSyncToken':'second'})
        return httpx.Response(200,json={'items':[{'id':'busy','start':{'dateTime':'2027-10-01T14:00:00Z'},'end':{'dateTime':'2027-10-01T15:00:00Z'}}],'nextSyncToken':'first'})
    mock_http(monkeypatch,handler)
    asyncio.run(google_reconcile.synchronize(main.database,org,'primary'))
    with main.database() as db:assert len(db.execute('SELECT * FROM external_busy WHERE organization_id=?',(org,)).fetchall())==1
    asyncio.run(google_reconcile.synchronize(main.database,org,'primary'))
    assert c.get(f'/api/appointments?organization_id={org}').json()==[]
    with main.database(write=True) as db:db.execute("UPDATE google_cursors SET sync_token='invalid' WHERE organization_id=?",(org,))
    asyncio.run(google_reconcile.synchronize(main.database,org,'primary'))
    assert steps==[None,'first','invalid',None]


def test_google_watch_signature_and_message_deduplication(workspace):
    c,main,org,*_=workspace
    with main.database(write=True) as db:
        db.execute('INSERT INTO google_watches(id,organization_id,calendar_id,token_hash,resource_id,expires_at) VALUES (?,?,?,?,?,?)',('watch',org,'primary',hashlib.sha256(b'secret').hexdigest(),'resource',int(time.time())+1000))
    headers={'X-Goog-Channel-ID':'watch','X-Goog-Channel-Token':'secret','X-Goog-Resource-ID':'resource','X-Goog-Message-Number':'1'}
    assert c.post('/api/google/notifications').status_code==403
    for _ in range(2):assert c.post('/api/google/notifications',headers=headers).status_code==200
    with main.database() as db:assert db.execute("SELECT COUNT(*) AS n FROM jobs WHERE kind='google_reconcile'").fetchone()['n']==1


def test_instagram_oauth_state_and_encrypted_connection(workspace,monkeypatch):
    c,main,org,*_=workspace;encrypted(monkeypatch)
    for k,v in {'INSTAGRAM_APP_ID':'app','INSTAGRAM_APP_SECRET':'secret','INSTAGRAM_REDIRECT_URI':'https://app.example/callback','META_GRAPH_VERSION':'v23.0'}.items():monkeypatch.setenv(k,v)
    from urllib.parse import urlparse,parse_qs
    authorization=c.post(f'/api/meta/oauth/instagram/start?organization_id={org}').json()
    state=parse_qs(urlparse(authorization['authorization_url']).query)['state'][0]
    def handler(request):
        if request.url.path.endswith('/oauth/access_token'):return httpx.Response(200,json={'access_token':'short','user_id':'123'})
        if request.url.path.endswith('/access_token'):return httpx.Response(200,json={'access_token':'long-secret','expires_in':5000000})
        if request.url.path.endswith('/me'):return httpx.Response(200,json={'user_id':'123'})
        if request.url.path.endswith('/subscribed_apps'):return httpx.Response(200,json={'success':True})
        raise AssertionError(request.url)
    mock_http(monkeypatch,handler)
    assert c.get('/api/meta/oauth/instagram/callback',params={'state':state,'code':'auth-code'}).status_code==200
    assert c.get('/api/meta/oauth/instagram/callback',params={'state':state,'code':'auth-code'}).status_code==403
    with main.database() as db:assert 'long-secret' not in db.execute('SELECT token_ciphertext FROM channel_credentials WHERE organization_id=?',(org,)).fetchone()['token_ciphertext']


def test_whatsapp_signup_rejects_foreign_phone_binding(workspace,monkeypatch):
    c,main,org,*_=workspace;encrypted(monkeypatch)
    for k,v in {'META_APP_ID':'app','META_APP_SECRET':'secret','META_WHATSAPP_CONFIG_ID':'config','META_GRAPH_VERSION':'v23.0'}.items():monkeypatch.setenv(k,v)
    config=c.post(f'/api/meta/oauth/whatsapp/start?organization_id={org}').json()
    def handler(request):
        if request.url.path.endswith('/oauth/access_token'):return httpx.Response(200,json={'access_token':'grant'})
        if request.url.path.endswith('/debug_token'):return httpx.Response(200,json={'data':{'is_valid':True,'app_id':'app','user_id':'owner'}})
        return httpx.Response(200,json={'data':[{'id':'999'}]})
    mock_http(monkeypatch,handler)
    r=c.post('/api/meta/oauth/whatsapp/complete',json={'state':config['state'],'code':'code','waba_id':'123','phone_number_id':'456'})
    assert r.status_code==422
    with main.database() as db:assert db.execute('SELECT * FROM meta_channels WHERE organization_id=?',(org,)).fetchall()==[]


def test_scheduler_heartbeats_and_export_do_not_expose_secrets(workspace):
    c,main,org,*_=workspace
    schedule(main.database)
    result=c.get(f'/api/operations/health?organization_id={org}').json()
    assert result['workers'][0]['healthy']
    output=c.get(f'/api/organizations/{org}/export')
    assert output.status_code==200
    for forbidden in ['password_hash','token_ciphertext','variables_ciphertext','csrf_hash']:assert forbidden not in output.text


def test_browser_dns_rejects_private_network(workspace,monkeypatch):
    monkeypatch.delenv('BROWSER_ALLOW_LOCAL_TEST',raising=False)
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**kw:[(2,1,6,'',('169.254.169.254',0))])
    with pytest.raises(HTTPException):resolver_rules({'https://approved.example'})


@pytest.mark.browser
@pytest.mark.skipif(os.getenv('SECRET_AI_TEST_BROWSER')!='1',reason='Chromium test enabled in browser CI')
def test_browser_demonstration_replay_and_booking_pipeline(workspace,monkeypatch):
    c,main,org,sid,_=workspace;encrypted(monkeypatch)
    bookings=[]
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            body=b'''<html><body><label>Customer<input id="customer"></label><button id="book" onclick="fetch('/book',{method:'POST',body:document.getElementById('customer').value}).then(r=>r.text()).then(t=>{document.getElementById('result').textContent='Confermato';document.getElementById('reference').textContent=t})">Prenota</button><div id="result"></div><div id="reference"></div></body></html>'''
            self.send_response(200);self.end_headers();self.wfile.write(body)
        def do_POST(self):
            bookings.append(self.rfile.read(int(self.headers['Content-Length'])).decode())
            self.send_response(200);self.end_headers();self.wfile.write(('REF-'+str(len(bookings))).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port)
    monkeypatch.setenv('BROWSER_ALLOWED_ORIGINS',origin);monkeypatch.setenv('BROWSER_ALLOW_LOCAL_TEST','1')
    pid=c.post(f'/api/browser/procedures?organization_id={org}',json={'name':'Prenota','origin':origin}).json()['id']
    async def exercise():
        runtime=Runtime(main.database)
        try:
            session=await runtime.open(pid,org);s=await runtime.get(session['id'],org)
            await runtime.act(s,{'action':'record'})
            await runtime.act(s,{'action':'fill','selector':'#customer','value':'Demo private name','parameter':'customer'})
            await runtime.act(s,{'action':'click','selector':'#book'})
            await runtime.act(s,{'action':'assert_text','selector':'#result','value':'Confermato'})
            await runtime.act(s,{'action':'capture','selector':'#reference','parameter':'booking_reference'})
            await runtime.act(s,{'action':'assert_text','selector':'#result','value':'Confermato'})
            await runtime.save(s);await runtime.close(session['id'])
            with main.database() as db:
                row=db.execute('SELECT * FROM browser_procedures WHERE id=?',(pid,)).fetchone()
                assert 'Demo private name' not in row['steps_json'] and '${customer}' in row['steps_json']
            assert c.post(f'/api/browser/procedures/{pid}/approve?organization_id={org}').status_code==200
            payload={'variables':{'customer':'Anna'},'idempotency_key':'browser-example-run'}
            rid=c.post(f'/api/browser/procedures/{pid}/run?organization_id={org}',json=payload).json()['id']
            assert (await runtime.execute(rid,org))['status']=='verified'
            assert (await runtime.execute(rid,org))['status']=='verified'
            assert c.post(f'/api/browser/procedures/{pid}/run?organization_id={org}',json=payload).json()['id']==rid
            assert bookings==['Demo private name','Anna']
            updated=c.put(f'/api/services/{sid}',json={'organization_id':org,'name':'Booking','duration_minutes':30,'automation':{'create':pid}})
            assert updated.status_code==200
            appointment=c.post('/api/appointments',json={'organization_id':org,'service_id':sid,'customer':'Luca','starts_at':'2027-11-05T10:00:00+01:00'}).json()
            assert appointment['sync_status']=='pending_browser'
            with main.database() as db:rid=db.execute('SELECT id FROM browser_runs WHERE appointment_id=?',(appointment['id'],)).fetchone()['id']
            assert (await runtime.execute(rid,org))['status']=='verified'
            saved=c.get(f'/api/appointments?organization_id={org}').json()[0]
            assert saved['status']=='confirmed' and saved['external_reference']=='REF-3'
            # An uncertain external outcome must not cause an automatic replay.
            with main.database(write=True) as db:
                p=db.execute('SELECT steps_json FROM browser_procedures WHERE id=?',(pid,)).fetchone()
                steps=json.loads(p['steps_json']);steps[-1]={'action':'assert_url','selector':'','value':'/never-confirmed'}
                db.execute('UPDATE browser_procedures SET steps_json=?,version=version+1 WHERE id=?',(json.dumps(steps),pid))
            pending=c.post(f'/api/browser/procedures/{pid}/run?organization_id={org}',json={'variables':{'customer':'Uncertain'},'idempotency_key':'uncertain-browser-run'}).json()['id']
            assert (await runtime.execute(pending,org))['status']=='attention'
            assert (await runtime.execute(pending,org))['status']=='attention'
            assert bookings.count('Uncertain')==1
            resolved=c.post(f'/api/browser/runs/{pending}/resolve?organization_id={org}',json={'outcome':'verified','evidence':'Verified the reference on the local test booking system','booking_reference':'REF-4'})
            assert resolved.status_code==200

        finally:
            for key in list(runtime.sessions):await runtime.close(key)
            if runtime.playwright:await runtime.playwright.stop()
    try:asyncio.run(exercise())
    finally:server.shutdown();server.server_close()


def test_whatsapp_signup_success_subscribes_registers_and_encrypts(workspace,monkeypatch):
    c,main,org,*_=workspace;encrypted(monkeypatch)
    for k,v in {'META_APP_ID':'app','META_APP_SECRET':'secret','META_WHATSAPP_CONFIG_ID':'config','META_GRAPH_VERSION':'v23.0'}.items():monkeypatch.setenv(k,v)
    config=c.post(f'/api/meta/oauth/whatsapp/start?organization_id={org}').json();calls=[]
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/oauth/access_token'):return httpx.Response(200,json={'access_token':'private-token','expires_in':5000000})
        if request.url.path.endswith('/debug_token'):return httpx.Response(200,json={'data':{'is_valid':True,'app_id':'app','user_id':'oauth-owner'}})
        if request.url.path.endswith('/phone_numbers'):return httpx.Response(200,json={'data':[{'id':'456'}]})
        return httpx.Response(200,json={'success':True})
    mock_http(monkeypatch,handler)
    payload={'state':config['state'],'code':'code','waba_id':'123','phone_number_id':'456','pin':'123456'}
    assert c.post('/api/meta/oauth/whatsapp/complete',json=payload).status_code==200
    assert any(p.endswith('/subscribed_apps') for p in calls) and any(p.endswith('/register') for p in calls)
    with main.database() as db:
        creds=db.execute('SELECT token_ciphertext,oauth_user_id FROM channel_credentials WHERE organization_id=?',(org,)).fetchone()
        assert 'private-token' not in creds['token_ciphertext'] and creds['oauth_user_id']=='oauth-owner'
    assert c.post('/api/meta/oauth/whatsapp/complete',json=payload).status_code==403


def test_automation_cannot_bind_another_company_procedure(workspace,monkeypatch):
    c,main,org,*_=workspace
    monkeypatch.setenv('BROWSER_ALLOWED_ORIGINS','https://authorized.example')
    pid=c.post(f'/api/browser/procedures?organization_id={org}',json={'name':'Private procedure','origin':'https://authorized.example'}).json()['id']
    with main.database(write=True) as db:db.execute('UPDATE browser_procedures SET approved=1 WHERE id=?',(pid,))
    outsider(c)
    other=c.post('/api/organizations',json={'name':'Other'}).json()['id']
    r=c.post('/api/services',json={'organization_id':other,'name':'Invalid','duration_minutes':30,'automation':{'create':pid}})
    assert r.status_code==422
    r=c.post(f'/api/browser/procedures/{pid}/run?organization_id={other}',json={'variables':{},'idempotency_key':'forbidden-run-id'})
    assert r.status_code==404


def test_billing_reconciliation_renewal_failed_payment_and_downgrade(workspace,monkeypatch):
    from app import billing
    from types import SimpleNamespace
    c,main,org,*_=workspace
    now=int(time.time())
    monkeypatch.setenv('SECRET_AI_PLANS_JSON',json.dumps({'starter':{'price_id':'price_starter','message_limit':10,'voice_seconds_limit':100},'pro':{'price_id':'price_pro','message_limit':100,'voice_seconds_limit':1000}}))
    with main.database(write=True) as db:db.execute("INSERT INTO billing_accounts(organization_id,stripe_customer_id) VALUES (?,'cus_test')",(org,))
    class Subscription:
        id='sub_test';status='active';cancel_at_period_end=False;price='price_pro';start=now;end=now+3600
        def to_dict(self):return {'items':{'data':[{'price':{'id':self.price},'current_period_start':self.start,'current_period_end':self.end}]}}
    subscription=Subscription();listing=SimpleNamespace(data=[subscription],has_more=False)
    monkeypatch.setattr(billing,'client',lambda:SimpleNamespace(v1=SimpleNamespace(subscriptions=SimpleNamespace(list=lambda data:listing))))
    async def reconcile():await billing.handlers(main.database)['stripe_reconcile']({'organization_id':org},{})
    asyncio.run(reconcile())
    assert c.get(f'/api/billing?organization_id={org}').json()['subscription']['plan']=='pro'
    subscription.status='past_due';asyncio.run(reconcile())
    monkeypatch.setenv('SECRET_AI_BILLING_REQUIRED','1')
    with pytest.raises(HTTPException):billing.consume(main.database,org,'messages',1,'declined-cycle')
    subscription.status='active';subscription.start=now+10;subscription.end=now+7200;subscription.price='price_starter';asyncio.run(reconcile())
    saved=c.get(f'/api/billing?organization_id={org}').json()['subscription']
    assert saved['plan']=='starter' and saved['period_end']==now+7200
    listing.data=[];asyncio.run(reconcile())
    assert c.get(f'/api/billing?organization_id={org}').json()['subscription']['status']=='canceled'
