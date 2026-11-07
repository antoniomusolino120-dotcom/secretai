"""Self-service Instagram OAuth and WhatsApp Embedded Signup completion."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel,Field
from app.auth import audit
from app.meta_channels import graph_base
from app.secrets import encrypt,decrypt

class WhatsAppComplete(BaseModel):
    state:str=Field(min_length=20,max_length=200)
    code:str=Field(min_length=1,max_length=4000)
    waba_id:str=Field(pattern='^[0-9]{1,40}$')
    phone_number_id:str=Field(pattern='^[0-9]{1,40}$')
    pin:str=Field(default='',pattern='^(?:[0-9]{6})?$')

async def request_json(client,method,url,**kwargs):
    try:
        r=await client.request(method,url,**kwargs);r.raise_for_status();data=r.json()
        if not isinstance(data,dict) or data.get('error'): raise ValueError()
        return data
    except (httpx.HTTPError,ValueError): raise HTTPException(502,'Meta non ha completato la richiesta; controlla autorizzazioni e configurazione')

def bind(db,org,provider,external_id,token,expiry,oauth_user_id=''):
    existing=db.execute('SELECT organization_id FROM meta_channels WHERE provider=? AND external_id=?',(provider,external_id)).fetchone()
    if existing and existing['organization_id']!=org: raise HTTPException(409,'Account già collegato a un’altra azienda')
    other=db.execute('SELECT 1 FROM meta_channels WHERE organization_id=? AND provider=? AND external_id<>?',(org,provider,external_id)).fetchone()
    if other: raise HTTPException(409,'Scollega prima il canale esistente')
    db.execute('INSERT INTO meta_channels(organization_id,provider,external_id) VALUES (?,?,?) ON CONFLICT(provider,external_id) DO NOTHING',(org,provider,external_id))
    bound=db.execute('SELECT organization_id FROM meta_channels WHERE provider=? AND external_id=?',(provider,external_id)).fetchone()
    if bound['organization_id']!=org: raise HTTPException(409,'Canale già associato')
    db.execute('INSERT INTO channel_credentials(organization_id,provider,token_ciphertext,expires_at) VALUES (?,?,?,?) ON CONFLICT(organization_id,provider) DO UPDATE SET token_ciphertext=excluded.token_ciphertext,expires_at=excluded.expires_at',(org,provider,encrypt(token),expiry))
    db.execute('UPDATE channel_credentials SET oauth_user_id=? WHERE organization_id=? AND provider=?',(oauth_user_id,org,provider))

def signed_request(value,secret):
    import base64
    try:
        signature,payload=value.split('.',1)
        raw=base64.urlsafe_b64decode(payload+'='*(-len(payload)%4))
        sig=base64.urlsafe_b64decode(signature+'='*(-len(signature)%4))
        if not hmac.compare_digest(sig,hmac.new(secret.encode(),payload.encode(),hashlib.sha256).digest()): raise ValueError()
        data=json.loads(raw)
        if data.get('algorithm','').upper()!='HMAC-SHA256': raise ValueError()
        return data
    except (ValueError,TypeError,KeyError): raise HTTPException(403,'Invalid signed request')

def install(database,current_user,require_org):
    router=APIRouter(tags=['meta-oauth'])
    def new_state(org,user,provider):
        state=secrets.token_urlsafe(40)
        with database(write=True,organization_id=org) as db:
            db.execute('DELETE FROM meta_oauth_states WHERE expires_at<? OR (organization_id=? AND user_id=? AND provider=?)',(int(time.time()),org,user,provider))
            db.execute('INSERT INTO meta_oauth_states VALUES (?,?,?,?,?)',(hashlib.sha256(state.encode()).hexdigest(),org,user,provider,int(time.time())+600))
        return state
    def consume(state,user,provider):
        with database(write=True) as db:
            row=db.execute('SELECT * FROM meta_oauth_states WHERE state_hash=? AND user_id=? AND provider=? AND expires_at>?',(hashlib.sha256(state.encode()).hexdigest(),user,provider,int(time.time()))).fetchone()
            if not row or db.execute('DELETE FROM meta_oauth_states WHERE state_hash=?',(hashlib.sha256(state.encode()).hexdigest(),)).rowcount!=1: raise HTTPException(403,'Stato OAuth scaduto o già utilizzato')
        require_org(user,row['organization_id'],owner=True)
        return row['organization_id']
    @router.post('/api/meta/oauth/{provider}/start')
    def start(provider:str,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        if provider not in {'instagram','whatsapp'}: raise HTTPException(422,'Canale non supportato')
        client_id=os.getenv('INSTAGRAM_APP_ID' if provider=='instagram' else 'META_APP_ID','')
        if not client_id: raise HTTPException(503,'Configura l’app Meta prima di collegare il canale')
        state=new_state(organization_id,user_id,provider)
        if provider=='instagram':
            redirect=os.getenv('INSTAGRAM_REDIRECT_URI','')
            if not redirect: raise HTTPException(503,'Redirect Instagram mancante')
            return {'authorization_url':'https://www.instagram.com/oauth/authorize?'+urlencode({'client_id':client_id,'redirect_uri':redirect,'response_type':'code','scope':'instagram_business_basic,instagram_business_manage_messages','state':state,'enable_fb_login':'0','force_authentication':'1'})}
        config_id=os.getenv('META_WHATSAPP_CONFIG_ID','')
        if not config_id: raise HTTPException(503,'Configurazione Embedded Signup mancante')
        return {'state':state,'app_id':client_id,'config_id':config_id,'version':os.getenv('META_GRAPH_VERSION') or 'v27.0','extras':json.loads(os.getenv('META_SIGNUP_EXTRAS_JSON','{}'))}
    @router.get('/api/meta/oauth/instagram/callback')
    async def instagram_callback(request:Request,state:str,code:str='',error:str='',user_id:int=Depends(current_user)):
        org=consume(state,user_id,'instagram')
        if error or not code: raise HTTPException(400,'Autorizzazione Instagram annullata')
        app_id=os.environ['INSTAGRAM_APP_ID'];secret=os.environ['INSTAGRAM_APP_SECRET']
        async with httpx.AsyncClient(timeout=20) as client:
            short=await request_json(client,'POST','https://api.instagram.com/oauth/access_token',data={'client_id':app_id,'client_secret':secret,'grant_type':'authorization_code','redirect_uri':os.environ['INSTAGRAM_REDIRECT_URI'],'code':code})
            # Instagram requires token exchange parameters in the query. HTTPX
            # access logging is disabled; tokens never reach app access logs.
            long=await request_json(client,'GET','https://graph.instagram.com/access_token',params={'grant_type':'ig_exchange_token','client_secret':secret,'access_token':short['access_token']})
            token=long['access_token'];expiry=int(time.time())+int(long['expires_in'])
            profile=await request_json(client,'GET',graph_base('instagram')+'/me',headers={'Authorization':'Bearer '+token},params={'fields':'user_id,id'})
            external_id=str(profile.get('user_id') or profile['id'])
            await request_json(client,'POST',graph_base('instagram')+'/'+external_id+'/subscribed_apps',headers={'Authorization':'Bearer '+token},data={'subscribed_fields':'messages,messaging_postbacks,messaging_seen'})
        with database(write=True,organization_id=org) as db:
            bind(db,org,'instagram',external_id,token,expiry,str(short.get('user_id') or external_id));audit(db,'meta.instagram_oauth_connected',user_id,org,external_id)
        return RedirectResponse('/#connections',303) if 'text/html' in request.headers.get('accept','') else {'connected':True}
    @router.post('/api/meta/oauth/whatsapp/complete')
    async def whatsapp_complete(data:WhatsAppComplete,user_id:int=Depends(current_user)):
        org=consume(data.state,user_id,'whatsapp');base=graph_base('whatsapp')
        async with httpx.AsyncClient(timeout=20) as client:
            token_result=await request_json(client,'POST',base+'/oauth/access_token',data={'client_id':os.environ['META_APP_ID'],'client_secret':os.environ['META_APP_SECRET'],'code':data.code})
            token=token_result['access_token'];headers={'Authorization':'Bearer '+token}
            debug=await request_json(client,'GET',base+'/debug_token',params={'input_token':token},headers={'Authorization':'Bearer '+os.environ['META_APP_ID']+'|'+os.environ['META_APP_SECRET']})
            if not debug.get('data',{}).get('is_valid') or str(debug['data'].get('app_id'))!=os.environ['META_APP_ID']:
                raise HTTPException(422,'Token non valido per questa app')
            oauth_uid=str(debug['data'].get('user_id',''))
            # Verify the selected phone is actually owned by the granted WABA.
            found=False;after=None
            for _ in range(20):
                phones=await request_json(client,'GET',base+'/'+data.waba_id+'/phone_numbers',headers=headers,params={'fields':'id','limit':100,**({'after':after} if after else {})})
                found=any(str(p['id'])==data.phone_number_id for p in phones.get('data',[]))
                if found or not phones.get('paging',{}).get('next'): break
                after=phones['paging']['cursors']['after']
            if not found: raise HTTPException(422,'Il numero selezionato non appartiene all’account autorizzato')
            await request_json(client,'POST',base+'/'+data.waba_id+'/subscribed_apps',headers=headers)
            if data.pin:
                await request_json(client,'POST',base+'/'+data.phone_number_id+'/register',headers=headers,json={'messaging_product':'whatsapp','pin':data.pin})
        expiry=int(time.time())+int(token_result['expires_in']) if token_result.get('expires_in') else None
        with database(write=True,organization_id=org) as db:
            bind(db,org,'whatsapp',data.phone_number_id,token,expiry,oauth_uid);audit(db,'meta.whatsapp_signup_connected',user_id,org,data.phone_number_id)
        return {'connected':True}
    @router.post('/api/meta/deauthorize/{provider}')
    async def deauthorize(provider:str,request:Request):
        from urllib.parse import parse_qs
        if provider not in {'instagram','whatsapp'}: raise HTTPException(422,'Invalid provider')
        secret=os.getenv('INSTAGRAM_APP_SECRET' if provider=='instagram' else 'META_APP_SECRET','')
        if not secret: raise HTTPException(503,'Meta app not configured')
        form=parse_qs((await request.body()).decode());value=form.get('signed_request',[''])[0]
        data=signed_request(value,secret);uid=str(data.get('user_id',''))
        if not uid: raise HTTPException(403,'Missing user')
        with database(write=True) as db:
            rows=[dict(r) for r in db.execute('SELECT organization_id FROM channel_credentials WHERE provider=? AND oauth_user_id=?',(provider,uid))]
            for row in rows:
                org=row['organization_id']
                db.execute('DELETE FROM channel_credentials WHERE organization_id=? AND provider=?',(org,provider))
                db.execute('DELETE FROM meta_channels WHERE organization_id=? AND provider=?',(org,provider))
                db.execute("UPDATE conversations SET status='human' WHERE organization_id=? AND channel=?",(org,provider))
                audit(db,'meta.revoked',organization_id=org,entity_id=provider)
        return {'ok':True}
    return router

def handlers(database):
    async def refresh(job,payload):
        org=job['organization_id']
        with database() as db: row=db.execute("SELECT * FROM channel_credentials WHERE organization_id=? AND provider='instagram'",(org,)).fetchone()
        if not row: return
        async with httpx.AsyncClient(timeout=20) as client:
            data=await request_json(client,'GET','https://graph.instagram.com/refresh_access_token',params={'grant_type':'ig_refresh_token','access_token':decrypt(row['token_ciphertext'])})
        with database(write=True,organization_id=org) as db:
            db.execute("UPDATE channel_credentials SET token_ciphertext=?,expires_at=? WHERE organization_id=? AND provider='instagram' AND token_ciphertext=?",(encrypt(data['access_token']),int(time.time())+int(data['expires_in']),org,row['token_ciphertext']))
    return {'meta_refresh':refresh}
