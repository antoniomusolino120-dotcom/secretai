"""Periodic reconciliation, heartbeats, data export and retention."""
import asyncio
import json
import os
import time
from fastapi import APIRouter,Depends,HTTPException
from app.booking import enqueue
from app.auth import audit


def heartbeat(database,name):
    with database(write=True) as db:
        db.execute('INSERT INTO runtime_heartbeats(name,seen_at) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET seen_at=excluded.seen_at',(name,int(time.time())))


def tick(database,name,period):
    bucket=int(time.time())//period
    with database(write=True) as db:
        result=db.execute('INSERT INTO scheduler_ticks(name,tick) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET tick=excluded.tick WHERE scheduler_ticks.tick<excluded.tick',(name,bucket))
    return result.rowcount==1,bucket


def schedule(database):
    heartbeat(database,'worker')
    due,bucket=tick(database,'reconcile',60)
    if not due:return
    now=int(time.time())
    with database(write=True) as db:
        db.execute("UPDATE browser_runs SET status='attention',result_json=?,variables_ciphertext='' WHERE status='running' AND created_at<?",(json.dumps({'reason':'Worker interrupted; verify external outcome before retry'}),now-300))
        for row in db.execute('SELECT organization_id,read_calendar_ids_json FROM google_connections').fetchall():
            org=row['organization_id']
            for cid in json.loads(row['read_calendar_ids_json']):
                enqueue(db,org,'google_reconcile',{'calendar_id':cid},f'google:poll:{org}:{cid}:{now//300}')
                watch=db.execute('SELECT 1 FROM google_watches WHERE organization_id=? AND calendar_id=? AND resource_id<>\'\' AND expires_at>?',(org,cid,now+86400)).fetchone()
                if not watch and os.getenv('SECRET_AI_PUBLIC_URL','').startswith('https://'):
                    enqueue(db,org,'google_watch',{'calendar_id':cid},f'google:watch:{org}:{cid}:{now//3600}')
        for row in db.execute('SELECT organization_id FROM billing_accounts').fetchall():
            org=row['organization_id'];enqueue(db,org,'stripe_reconcile',{},f'stripe:poll:{org}:{now//3600}')
        for row in db.execute('SELECT organization_id,provider,expires_at FROM channel_credentials WHERE expires_at IS NOT NULL').fetchall():
            if row['expires_at']<=now:
                db.execute("UPDATE conversations SET status='human' WHERE organization_id=? AND channel=?",(row['organization_id'],row['provider']))
            elif row['provider']=='instagram' and row['expires_at']<now+7*86400:
                enqueue(db,row['organization_id'],'meta_refresh',{},f'meta:refresh:{row["organization_id"]}:{now//21600}')
        retention=int(os.getenv('SECRET_AI_RETENTION_DAYS','0'))
        if retention>0:
            cutoff=now-retention*86400
            db.execute('DELETE FROM messages WHERE created_at<?',(cutoff,))
            db.execute('DELETE FROM meta_messages WHERE received_at<?',(cutoff,))
            db.execute('DELETE FROM booking_proposals WHERE expires_at<?',(cutoff,))
        db.execute('DELETE FROM google_watches WHERE expires_at<?',(now,))
        db.execute('DELETE FROM meta_oauth_states WHERE expires_at<?',(now,))
        db.execute('DELETE FROM auth_challenges WHERE expires_at<?',(now,))
        db.execute('DELETE FROM sessions WHERE expires_at<?',(now,))


def install(database,current_user,require_org):
    router=APIRouter(tags=['operations'])
    @router.get('/api/operations/health')
    def health(organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database() as db:
            heartbeats=[{'name':r['name'],'healthy':r['seen_at']>time.time()-180,'seen_at':r['seen_at']} for r in db.execute('SELECT * FROM runtime_heartbeats')]
            failed=db.execute("SELECT COUNT(*) AS n FROM jobs WHERE organization_id=? AND status IN ('attention','failed')",(organization_id,)).fetchone()['n']
            pending=db.execute("SELECT COUNT(*) AS n FROM jobs WHERE organization_id=? AND status='pending' AND available_at<?",(organization_id,int(time.time())-180)).fetchone()['n']
        return {'workers':heartbeats,'failed_jobs':failed,'delayed_jobs':pending,'retention_days':int(os.getenv('SECRET_AI_RETENTION_DAYS','0'))}
    @router.get('/api/organizations/{organization_id}/export')
    def export(organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database() as db:
            output={}
            for table,columns in [('contacts','id,name,email,phone,notes,created_at'),('appointments','id,customer,service_id,starts_at,ends_at,status,contact_id'),('conversations','id,contact_id,channel,status,updated_at'),('messages','id,conversation_id,direction,body,created_at,delivery_status')]:
                output[table]=[dict(r) for r in db.execute(f'SELECT {columns} FROM {table} WHERE organization_id=?',(organization_id,))]
        return output
    @router.delete('/api/contacts/{contact_id}/personal-data')
    def erase(contact_id:int,organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database(write=True,organization_id=organization_id) as db:
            if not db.execute('SELECT 1 FROM contacts WHERE id=? AND organization_id=?',(contact_id,organization_id)).fetchone():raise HTTPException(404,'Cliente inesistente')
            convs=db.execute('SELECT id,channel,external_id FROM conversations WHERE organization_id=? AND contact_id=?',(organization_id,contact_id)).fetchall()
            for conv in convs:
                db.execute('DELETE FROM messages WHERE organization_id=? AND conversation_id=?',(organization_id,conv['id']))
                db.execute('DELETE FROM meta_messages WHERE organization_id=? AND provider=? AND sender_id=?',(organization_id,conv['channel'],conv['external_id']))
                db.execute("UPDATE conversations SET external_id=?,status='closed',identity_verified=0 WHERE id=? AND organization_id=?",('erased:'+str(conv['id']),conv['id'],organization_id))
                db.execute('DELETE FROM booking_proposals WHERE organization_id=? AND conversation_id=?',(organization_id,conv['id']))
            db.execute("UPDATE contacts SET name='Cliente anonimizzato',email='',phone='',notes='' WHERE id=? AND organization_id=?",(contact_id,organization_id))
            db.execute("UPDATE appointments SET customer='Cliente anonimizzato' WHERE contact_id=? AND organization_id=?",(contact_id,organization_id))
            audit(db,'contact.personal_data_erased',user_id,organization_id,contact_id)
        return {'erased':True,'message':'Contenuti personali rimossi; restano riferimenti operativi anonimizzati'}
    return router
