"""Versioned browser teaching API. Credentials and sessions never enter AI prompts."""
import json
import hashlib
import os
import secrets
import time
import uuid
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.auth import audit
from app.booking import enqueue
from app.secrets import encrypt

class Procedure(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    origin: str = Field(min_length=5,max_length=500)
class Resolution(BaseModel):
    outcome: str = Field(pattern='^(verified|not_executed)$')
    evidence: str = Field(min_length=5,max_length=500)
    booking_reference: str = Field(default='',max_length=500)

class Run(BaseModel):
    variables: dict[str,str] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8,max_length=100)
class BrowserAction(BaseModel):
    action: str = Field(pattern='^(record|inspect|click|fill|select|capture|assert_text|assert_url|goto)$')
    selector: str = Field(default='',max_length=1000)
    x: int | None = Field(default=None,ge=0,le=1280)
    y: int | None = Field(default=None,ge=0,le=900)
    value: str = Field(default='',max_length=4000)
    format: str = Field(default='text',pattern='^(text|date|time|date_it|datetime_local)$')
    parameter: str = Field(default='',pattern='^[a-zA-Z0-9_]*$',max_length=80)

async def rpc(method,path,data=None):
    base=os.getenv('BROWSER_WORKER_URL','').rstrip('/')
    token=os.getenv('SECRET_AI_INTERNAL_TOKEN','')
    if not base or len(token)<32: raise HTTPException(503,'Browser worker non configurato')
    try:
        async with httpx.AsyncClient(timeout=100,trust_env=False) as client:
            r=await client.request(method,base+path,json=data,headers={'Authorization':'Bearer '+token})
            if r.status_code>=400: raise HTTPException(r.status_code,'Operazione browser non riuscita; controlla sessione, dominio e stato')
            return r.json()
    except httpx.HTTPError: raise HTTPException(503,'Browser worker non disponibile')

def install(database,current_user,require_org):
    router=APIRouter(tags=['computer-use'])
    def procedure(db,pid,oid):
        p=db.execute('SELECT * FROM browser_procedures WHERE id=? AND organization_id=?',(pid,oid)).fetchone()
        if not p: raise HTTPException(404,'Procedura inesistente')
        return p
    @router.get('/api/browser/procedures')
    def procedures(organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database() as db:
            return [dict(r) for r in db.execute('SELECT id,name,origin,version,approved,steps_json,updated_at FROM browser_procedures WHERE organization_id=?',(organization_id,))]
    @router.post('/api/browser/procedures')
    def create(organization_id:int,data:Procedure,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        from app.browser_worker import validate_origin
        origin=validate_origin(data.origin); pid=uuid.uuid4().hex
        with database(write=True,organization_id=organization_id) as db:
            db.execute('INSERT INTO browser_procedures(id,organization_id,name,origin,updated_at) VALUES (?,?,?,?,?)',(pid,organization_id,data.name,origin,int(time.time())))
            audit(db,'browser.procedure_created',user_id,organization_id,pid)
        return {'id':pid}
    @router.post('/api/browser/procedures/{pid}/teach')
    async def teach(pid:str,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database() as db: procedure(db,pid,organization_id)
        return await rpc('POST','/sessions',{'procedure_id':pid,'organization_id':organization_id})
    @router.get('/api/browser/sessions/{sid}')
    async def snapshot(sid:str,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        return await rpc('GET',f'/sessions/{sid}?organization_id={organization_id}')
    @router.post('/api/browser/sessions/{sid}/action')
    async def action(sid:str,organization_id:int,data:BrowserAction,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        return await rpc('POST',f'/sessions/{sid}/action?organization_id={organization_id}',data.model_dump())
    @router.post('/api/browser/sessions/{sid}/save')
    async def save(sid:str,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        return await rpc('POST',f'/sessions/{sid}/save?organization_id={organization_id}')
    @router.delete('/api/browser/sessions/{sid}')
    async def close(sid:str,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        return await rpc('DELETE',f'/sessions/{sid}?organization_id={organization_id}')
    @router.post('/api/browser/procedures/{pid}/approve')
    def approve(pid:str,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database(write=True,organization_id=organization_id) as db:
            p=procedure(db,pid,organization_id); steps=json.loads(p['steps_json'])
            if not steps or not steps[-1]['action'].startswith('assert_'): raise HTTPException(422,'La procedura deve terminare con una verifica dell’esito')
            db.execute('UPDATE browser_procedures SET approved=1 WHERE id=? AND organization_id=?',(pid,organization_id))
            audit(db,'browser.procedure_approved',user_id,organization_id,pid)
        return {'ok':True}
    @router.post('/api/browser/procedures/{pid}/run')
    def run(pid:str,organization_id:int,data:Run,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        if len(data.variables)>50 or any(len(k)>80 or len(v)>4000 for k,v in data.variables.items()): raise HTTPException(422,'Parametri troppo grandi')
        with database(write=True,organization_id=organization_id) as db:
            p=procedure(db,pid,organization_id)
            if not p['approved']: raise HTTPException(409,'Approva prima la versione dimostrata')
            previous=db.execute('SELECT id,procedure_id,request_hash FROM browser_runs WHERE organization_id=? AND idempotency_key=?',(organization_id,data.idempotency_key)).fetchone()
            if previous:
                from app.secrets import decrypt
                if previous['procedure_id']!=pid or previous['request_hash']!=hashlib.sha256(json.dumps(data.variables,sort_keys=True).encode()).hexdigest(): raise HTTPException(409,'Chiave già usata con altri dati')
                return {'id':previous['id']}
            rid=uuid.uuid4().hex
            db.execute('INSERT INTO browser_runs(id,organization_id,procedure_id,version,idempotency_key,request_hash,variables_ciphertext,created_at) VALUES (?,?,?,?,?,?,?,?)',(rid,organization_id,pid,p['version'],data.idempotency_key,hashlib.sha256(json.dumps(data.variables,sort_keys=True).encode()).hexdigest(),encrypt(json.dumps(data.variables)),int(time.time())))
            enqueue(db,organization_id,'browser_run',{'run_id':rid},'browser:'+rid)
            audit(db,'browser.run_requested',user_id,organization_id,rid)
        return {'id':rid}
    @router.get('/api/browser/runs')
    def runs(organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database() as db:
            return [dict(r) for r in db.execute('SELECT id,procedure_id,version,status,step,result_json,created_at FROM browser_runs WHERE organization_id=? ORDER BY created_at DESC LIMIT 100',(organization_id,))]
    @router.post('/api/browser/runs/{rid}/resolve')
    def resolve(rid:str,organization_id:int,data:Resolution,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database(write=True,organization_id=organization_id) as db:
            run=db.execute('SELECT * FROM browser_runs WHERE id=? AND organization_id=?',(rid,organization_id)).fetchone()
            if not run or run['status']!='attention': raise HTTPException(409,'Solo esecuzioni sospese possono essere risolte manualmente')
            result={'operator_verified':True,'evidence':data.evidence,'captures':{'booking_reference':data.booking_reference}}
            db.execute('UPDATE browser_runs SET status=?,result_json=?,variables_ciphertext=? WHERE id=? AND organization_id=?',(data.outcome,json.dumps(result),'',rid,organization_id))
            if data.outcome=='not_executed' and run['appointment_id']:
                aid=run['appointment_id']
                if run['operation']=='create': db.execute("UPDATE appointments SET status='cancelled',sync_status='local' WHERE id=? AND organization_id=?",(aid,organization_id))
                else:
                    hold=db.execute('SELECT starts_at,ends_at FROM appointment_holds WHERE organization_id=? AND appointment_id=? ORDER BY starts_at LIMIT 1',(organization_id,aid)).fetchone()
                    if hold: db.execute('UPDATE appointments SET starts_at=?,ends_at=? WHERE id=? AND organization_id=?',(hold['starts_at'],hold['ends_at'],aid,organization_id))
                    db.execute("UPDATE appointments SET status='confirmed',sync_status=CASE WHEN external_event_id IS NULL THEN 'local' ELSE 'synced' END WHERE id=? AND organization_id=?",(aid,organization_id))
                db.execute('DELETE FROM appointment_holds WHERE organization_id=? AND appointment_id=?',(organization_id,aid))
            if data.outcome=='verified' and run['appointment_id']:
                from app.browser_worker import finish_appointment
                finish_appointment(database,organization_id,run['appointment_id'],run['operation'],'verified',result,db=db)
            audit(db,'browser.run_resolved',user_id,organization_id,rid)
        return {'resolved':True}
    return router

def handlers(database):
    async def execute(job,payload):
        from app.jobs import AttentionRequired
        result=await rpc('POST','/runs/'+payload['run_id'],{'organization_id':job['organization_id']})
        if result['status']!='verified': raise AttentionRequired('Browser procedure needs human review')
    return {'browser_run':execute}

def enqueue_booking_automation(db,org_id,appointment_id,operation):
    """Called in the same transaction that reserves or mutates the local slot."""
    import hashlib
    row=db.execute('SELECT a.*,s.name AS service_name,s.automation_json FROM appointments a JOIN services s ON s.id=a.service_id AND s.organization_id=a.organization_id WHERE a.id=? AND a.organization_id=?',(appointment_id,org_id)).fetchone()
    mapping=json.loads(row['automation_json']);pid=mapping.get(operation)
    if not mapping:return False
    if not pid:raise HTTPException(409,'Configura la procedura del gestionale per questa operazione')
    procedure=db.execute('SELECT * FROM browser_procedures WHERE id=? AND organization_id=? AND approved=1',(pid,org_id)).fetchone()
    if not procedure:raise HTTPException(409,'La procedura del gestionale deve essere approvata')
    contact=db.execute('SELECT email,phone FROM contacts WHERE id=? AND organization_id=?',(row['contact_id'],org_id)).fetchone() if row['contact_id'] else None
    from datetime import datetime
    from zoneinfo import ZoneInfo
    timezone=db.execute('SELECT timezone FROM organizations WHERE id=?',(org_id,)).fetchone()['timezone']
    variables={'customer':row['customer'],'starts_at':datetime.fromisoformat(row['starts_at']).astimezone(ZoneInfo(timezone)).isoformat(),'ends_at':datetime.fromisoformat(row['ends_at']).astimezone(ZoneInfo(timezone)).isoformat(),'service':row['service_name'],'appointment_id':str(appointment_id),'booking_reference':row['external_reference'],'email':contact['email'] if contact else '', 'phone':contact['phone'] if contact else ''}
    rid=uuid.uuid4().hex;key=f'booking:{appointment_id}:{operation}:{time.time_ns()}'
    db.execute('INSERT INTO browser_runs(id,organization_id,procedure_id,version,idempotency_key,request_hash,appointment_id,operation,variables_ciphertext,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,org_id,pid,procedure['version'],key,hashlib.sha256(json.dumps(variables,sort_keys=True).encode()).hexdigest(),appointment_id,operation,encrypt(json.dumps(variables)),int(time.time())))
    db.execute("UPDATE appointments SET status=?,sync_status='pending_browser' WHERE id=? AND organization_id=?",('cancelling' if operation=='cancel' else 'pending_sync',appointment_id,org_id))
    enqueue(db,org_id,'browser_run',{'run_id':rid},'browser:'+rid)
    return True
