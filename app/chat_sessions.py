"""Durable web history and idempotent turns; inference runs outside transactions."""
import hashlib
import json
import secrets
import time
from fastapi import HTTPException

def conversation(db,org,uid,create=False):
    external=f'assistant:{uid}'
    row=db.execute("SELECT * FROM conversations WHERE organization_id=? AND channel='web' AND external_id=?",(org,external)).fetchone()
    if not row and create:
        db.execute("INSERT INTO conversations(organization_id,channel,external_id,updated_at) VALUES (?,'web',?,?)",(org,external,int(time.time())))
        row=conversation(db,org,uid)
    return row

def history(database,org,uid):
    with database() as db:
        conv=conversation(db,org,uid)
        messages=[dict(r) for r in db.execute('SELECT direction,body,created_at FROM messages WHERE organization_id=? AND conversation_id=? ORDER BY id DESC LIMIT 100',(org,conv['id']))][::-1] if conv else []
    return {'conversation_id':conv['id'] if conv else None,'status':conv['status'] if conv else 'ai','messages':messages}

async def web_turn(database,data,uid,key,responder):
    key=key or secrets.token_urlsafe(24);org=data.organization_id;now=int(time.time())
    if not 8<=len(key)<=150:raise HTTPException(422,'Idempotency-Key deve avere tra 8 e 150 caratteri')
    fingerprint=hashlib.sha256(json.dumps(data.model_dump(mode='json'),sort_keys=True).encode()).hexdigest()
    with database(write=True,organization_id=org) as db:
        previous=db.execute('SELECT * FROM chat_turns WHERE organization_id=? AND user_id=? AND request_key=?',(org,uid,key)).fetchone()
        if previous:
            if previous['request_hash']!=fingerprint:raise HTTPException(409,'Chiave già usata per un altro messaggio')
            if previous['status']=='done':return json.loads(previous['response_json'])
            raise HTTPException(409,'Messaggio già ricevuto; aggiorna la conversazione')
        conv=db.execute("SELECT * FROM conversations WHERE id=? AND organization_id=? AND channel='web'",(data.conversation_id,org)).fetchone() if data.conversation_id else conversation(db,org,uid,True)
        if not conv:raise HTTPException(404,'Conversazione web inesistente')
        if conv['status']!='ai':raise HTTPException(409,'Riattiva la conversazione AI dall’inbox per continuare')
        cid=conv['id']
        db.execute("UPDATE chat_turns SET status='interrupted' WHERE organization_id=? AND conversation_id=? AND status='running' AND created_at<?",(org,cid,now-120))
        if db.execute("SELECT 1 FROM chat_turns WHERE organization_id=? AND conversation_id=? AND status='running'",(org,cid)).fetchone():raise HTTPException(409,'Attendi la risposta al messaggio precedente')
        db.execute('INSERT INTO chat_turns(organization_id,user_id,request_key,conversation_id,request_hash,created_at) VALUES (?,?,?,?,?,?)',(org,uid,key,cid,fingerprint,now))
        db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at) VALUES (?,?,'inbound',?,?)",(org,cid,data.message,now))
    try:
        from app.billing import consume
        consume(database,org,'messages',1,f'web:{uid}:{key}')
        result=await responder(database,org,data.message,conversation_id=cid,user_id=uid)
    except BaseException:
        with database(write=True,organization_id=org) as db:db.execute("UPDATE chat_turns SET status='interrupted' WHERE organization_id=? AND user_id=? AND request_key=?",(org,uid,key))
        raise
    with database(write=True,organization_id=org) as db:
        current=db.execute('SELECT status FROM conversations WHERE id=? AND organization_id=?',(cid,org)).fetchone()
        turn=db.execute('SELECT status FROM chat_turns WHERE organization_id=? AND user_id=? AND request_key=?',(org,uid,key)).fetchone()
        if turn['status']!='running':raise HTTPException(409,'Risposta scaduta; aggiorna la conversazione')
        if current['status']!='ai' and result['mode'] not in {'human','offline'}:result={'mode':'human','reply':'Conversazione presa in carico da un operatore. Controlla l’agenda per eventuali operazioni.'}
        result={**result,'conversation_id':cid}
        db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,delivery_status) VALUES (?,?,'outbound',?,?,'sent')",(org,cid,result['reply'],int(time.time())))
        db.execute("UPDATE chat_turns SET status='done',response_json=? WHERE organization_id=? AND user_id=? AND request_key=?",(json.dumps(result),org,uid,key))
        db.execute('UPDATE conversations SET updated_at=? WHERE id=? AND organization_id=?',(int(time.time()),cid,org))
    return result
