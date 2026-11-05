"""Incremental Calendar sync, expiring watches and fail-closed reconciliation."""
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime,timezone,timedelta
from urllib.parse import quote
import httpx
from fastapi import APIRouter,Depends,Header,HTTPException,Request
from app.google_calendar import access_token,CALENDAR_URL,google_request
from app.booking import enqueue,utc

async def synchronize(database,org_id,calendar_id):
    token=await access_token(database,org_id)
    with database() as db:
        cursor=db.execute('SELECT sync_token FROM google_cursors WHERE organization_id=? AND calendar_id=?',(org_id,calendar_id)).fetchone()
        cursor=cursor['sync_token'] if cursor else ''
    expected_cursor=cursor
    events=[];next_token=None;page=None;full=not cursor
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            params={'maxResults':2500,'showDeleted':'true','singleEvents':'true'}
            if cursor: params['syncToken']=cursor
            if page: params['pageToken']=page
            r=await client.get(CALENDAR_URL+'/calendars/'+quote(calendar_id,safe='')+'/events',headers={'Authorization':'Bearer '+token},params=params)
            if r.status_code==410 and cursor:
                cursor='';page=None;events=[];full=True;continue
            r.raise_for_status();data=r.json();events.extend(data.get('items',[]))
            page=data.get('nextPageToken')
            if not page:
                next_token=data['nextSyncToken'];break
    with database(write=True,organization_id=org_id) as db:
        # A stale concurrent sync cannot roll the cursor backwards.
        current=db.execute('SELECT sync_token FROM google_cursors WHERE organization_id=? AND calendar_id=?',(org_id,calendar_id)).fetchone()
        if (current['sync_token'] if current else '')!=expected_cursor: return
        selected=db.execute('SELECT calendar_id,read_calendar_ids_json FROM google_connections WHERE organization_id=?',(org_id,)).fetchone()
        if not selected or calendar_id not in json.loads(selected['read_calendar_ids_json']): return
        if full: db.execute('DELETE FROM external_busy WHERE organization_id=? AND calendar_id=?',(org_id,calendar_id))
        for e in events:
            eid=e.get('id')
            if not eid: continue
            db.execute('DELETE FROM external_busy WHERE organization_id=? AND calendar_id=? AND event_id=?',(org_id,calendar_id,eid))
            appointment=db.execute('SELECT * FROM appointments WHERE organization_id=? AND external_event_id=?',(org_id,eid)).fetchone() if calendar_id==selected['calendar_id'] else None
            deleted=e.get('status')=='cancelled'
            start=e.get('start',{});end=e.get('end',{})
            start_value=start.get('dateTime') or (start.get('date')+'T00:00:00+00:00' if start.get('date') else None)
            end_value=end.get('dateTime') or (end.get('date')+'T00:00:00+00:00' if end.get('date') else None)
            if appointment:
                # A local write in flight wins until its outbox operation is resolved.
                if appointment['sync_status']=='synced':
                    if deleted: db.execute("UPDATE appointments SET status='cancelled' WHERE id=? AND organization_id=?",(appointment['id'],org_id))
                    elif start_value and end_value:
                        a=utc(datetime.fromisoformat(start_value)).isoformat();b=utc(datetime.fromisoformat(end_value)).isoformat()
                        conflict=db.execute("SELECT 1 FROM appointments WHERE organization_id=? AND id<>? AND status<>'cancelled' AND starts_at<? AND ends_at>?",(org_id,appointment['id'],b,a)).fetchone()
                        db.execute('UPDATE appointments SET starts_at=?,ends_at=?,sync_status=? WHERE id=? AND organization_id=?',(a,b,'attention' if conflict else 'synced',appointment['id'],org_id))
                continue
            if not deleted and e.get('transparency')!='transparent' and start_value and end_value:
                a=utc(datetime.fromisoformat(start_value)).isoformat();b=utc(datetime.fromisoformat(end_value)).isoformat()
                db.execute('INSERT INTO external_busy(organization_id,calendar_id,event_id,starts_at,ends_at) VALUES (?,?,?,?,?)',(org_id,calendar_id,eid,a,b))
        db.execute('INSERT INTO google_cursors(organization_id,calendar_id,sync_token,updated_at) VALUES (?,?,?,?) ON CONFLICT(organization_id,calendar_id) DO UPDATE SET sync_token=excluded.sync_token,updated_at=excluded.updated_at',(org_id,calendar_id,next_token,int(time.time())))

async def watch(database,org_id,calendar_id,public_url):
    token=await access_token(database,org_id)
    wid=str(uuid.uuid4());secret=secrets.token_urlsafe(32)
    # Save before the request: Google may send its sync notification immediately.
    with database(write=True,organization_id=org_id) as db:
        db.execute('INSERT INTO google_watches(id,organization_id,calendar_id,token_hash,resource_id,expires_at) VALUES (?,?,?,?,?,?)',(wid,org_id,calendar_id,hashlib.sha256(secret.encode()).hexdigest(),'',int(time.time())+600))
    async with httpx.AsyncClient(timeout=20) as client:
        result=await google_request(client,'POST','/calendars/'+quote(calendar_id,safe='')+'/events/watch',token,json={'id':wid,'type':'web_hook','address':public_url.rstrip('/')+'/api/google/notifications','token':secret,'expiration':str((int(time.time())+6*86400)*1000)})
    with database(write=True,organization_id=org_id) as db:
        db.execute('UPDATE google_watches SET resource_id=?,expires_at=? WHERE id=?',(result['resourceId'],int(result['expiration'])//1000,wid))
        old=[dict(r) for r in db.execute('SELECT id,resource_id FROM google_watches WHERE organization_id=? AND calendar_id=? AND id<>?',(org_id,calendar_id,wid))]
    # Explicitly retire replaced channels, rather than accumulating watch leaks.
    async with httpx.AsyncClient(timeout=20) as client:
        for previous in old:
            if previous['resource_id']:
                response=await client.post(CALENDAR_URL+'/channels/stop',headers={'Authorization':'Bearer '+token},json={'id':previous['id'],'resourceId':previous['resource_id']})
                if response.status_code not in {200,204,404,410}: continue
            with database(write=True) as db: db.execute('DELETE FROM google_watches WHERE id=?',(previous['id'],))


def install(database,current_user,require_org):
    router=APIRouter(tags=['google-sync'])
    @router.post('/api/google/synchronize')
    def request_sync(organization_id:int,user_id:int=Depends(current_user)):
        require_org(user_id,organization_id,owner=True)
        with database(write=True,organization_id=organization_id) as db:
            row=db.execute('SELECT read_calendar_ids_json FROM google_connections WHERE organization_id=?',(organization_id,)).fetchone()
            if not row: raise HTTPException(404,'Google non collegato')
            for cid in json.loads(row['read_calendar_ids_json']): enqueue(db,organization_id,'google_reconcile',{'calendar_id':cid},f'google-sync:{organization_id}:{cid}:{time.time_ns()}')
        return {'queued':True}
    @router.post('/api/google/notifications')
    def notification(request:Request):
        wid=request.headers.get('X-Goog-Channel-ID','');token=request.headers.get('X-Goog-Channel-Token','')
        try: number=int(request.headers.get('X-Goog-Message-Number','0'))
        except ValueError: raise HTTPException(400,'Invalid message number')
        with database(write=True) as db:
            row=db.execute('SELECT * FROM google_watches WHERE id=? AND expires_at>?',(wid,int(time.time()))).fetchone()
            if not row or not hmac.compare_digest(row['token_hash'],hashlib.sha256(token.encode()).hexdigest()): raise HTTPException(403,'Invalid channel')
            resource=request.headers.get('X-Goog-Resource-ID','')
            if row['resource_id'] and resource!=row['resource_id']: raise HTTPException(403,'Invalid resource')
            if number>row['last_message']:
                db.execute('UPDATE google_watches SET last_message=? WHERE id=?',(number,wid))
                enqueue(db,row['organization_id'],'google_reconcile',{'calendar_id':row['calendar_id']},f'google-notify:{wid}:{number}')
        return {'ok':True}
    return router

def handlers(database):
    async def reconcile(job,payload): await synchronize(database,job['organization_id'],payload['calendar_id'])
    async def renew(job,payload):
        import os
        public=os.getenv('SECRET_AI_PUBLIC_URL','')
        if public.startswith('https://'): await watch(database,job['organization_id'],payload['calendar_id'],public)
    return {'google_reconcile':reconcile,'google_watch':renew}
