import json
import asyncio
import httpx
from test_adapters import mock_http
from conftest import outsider

QUESTIONS=[{'id':'people','label':'Quante persone siete?','type':'number','required':True},
           {'id':'room','label':'Interno o esterno?','type':'choice','options':['Interno','Esterno'],'required':True},
           {'id':'notes','label':'Vuoi aggiungere una nota?','type':'text','required':False}]
REQUEST='Vorrei prenotare il 1 settembre 2027 alle 10, a nome Anna Verdi'

def configure(c,org,sid,questions=QUESTIONS):
    return c.put(f'/api/services/{sid}',json={'organization_id':org,'name':'Tavolo ristorante','duration_minutes':60,'description':'Menu alla carta e tavoli in giardino.','aliases':['cena','pranzo'],'intake_questions':questions})

def proposal_mock(monkeypatch,sid):
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'tool_calls':[{'function':{'name':'propose_booking','arguments':{'service_id':sid,'starts_at':'2030-01-01T10:00:00Z','customer':'Inventato','intake_answers':{'people':99,'room':'Interno'}}}}]}})
    mock_http(monkeypatch,handler)
    return calls

def test_owner_catalogue_and_typed_answers_are_enforced_by_booking_backend(workspace):
    c,_,org,sid,_=workspace
    assert configure(c,org,sid).status_code==200
    service=c.get(f'/api/services?organization_id={org}').json()[0]
    assert service['description'].startswith('Menu') and json.loads(service['aliases_json'])==['cena','pranzo']
    body={'organization_id':org,'service_id':sid,'customer':'Anna','starts_at':'2027-09-01T10:00:00+02:00'}
    assert c.post('/api/appointments',json=body).status_code==422
    for answers in [{'people':'molti','room':'Interno'},{'people':4,'room':'Roof'},{'people':True,'room':'Interno'},{'people':4,'room':'Interno','unknown':'private'}]:
        assert c.post('/api/appointments',json={**body,'intake_answers':answers}).status_code==422
    assert c.post('/api/appointments',json={**body,'intake_answers':{'people':4,'room':'interno'}}).status_code==200
    saved=c.get(f'/api/appointments?organization_id={org}').json()[0]
    snapshot=json.loads(saved['intake_json']);assert snapshot[0]['answer']==4 and snapshot[1]['answer']=='Interno'
    configure(c,org,sid,[])
    assert json.loads(c.get(f'/api/appointments?organization_id={org}').json()[0]['intake_json'])==snapshot
    outsider(c);assert configure(c,org,sid).status_code==403

def test_intake_uses_real_customer_answers_not_guessed_model_arguments(workspace,monkeypatch):
    c,_,org,sid,_=workspace;configure(c,org,sid);calls=proposal_mock(monkeypatch,sid)
    serial=[0]
    def say(text,key=None):
        serial[0]+=1
        r=c.post('/api/chat',json={'organization_id':org,'message':text},headers={'Idempotency-Key':key or 'turn-'+str(serial[0])+'-'+text})
        assert r.status_code==200,r.text
        return r.json()
    assert say(REQUEST)['question_id']=='people'
    assert say('salta')['mode']=='intake'
    assert say('siamo in quattro')['question_id']=='room'
    assert say('quanto costa?')['mode']=='tool'
    assert say('Esterno')['question_id']=='notes'
    assert say('salta')['mode']=='proposal'
    assert not c.get(f'/api/appointments?organization_id={org}').json()
    result=say('Sì, confermo!','confirm-unique-0001')
    assert result['appointment']['status']=='confirmed'
    assert say('Sì, confermo!','confirm-unique-0001')==result
    saved=c.get(f'/api/appointments?organization_id={org}').json()
    assert len(saved)==1 and saved[0]['customer']=='Anna Verdi'
    assert saved[0]['starts_at']=='2027-09-01T08:00:00+00:00'
    assert [(a['id'],a['answer']) for a in json.loads(saved[0]['intake_json'])]==[('people',4),('room','Esterno')]
    assert len(calls)==1
    assert len(c.get(f'/api/chat?organization_id={org}').json()['messages'])==14

def test_no_is_an_answer_inside_an_intake_and_questions_can_change(workspace,monkeypatch):
    c,_,org,sid,_=workspace
    configure(c,org,sid,[{'id':'previous','label':'Hai già effettuato una visita?','type':'text','required':True}]);proposal_mock(monkeypatch,sid)
    c.post('/api/chat',json={'organization_id':org,'message':REQUEST})
    result=c.post('/api/chat',json={'organization_id':org,'message':'No'}).json()
    assert result['mode']=='proposal'
    configure(c,org,sid,QUESTIONS)
    assert c.post('/api/chat',json={'organization_id':org,'message':'confermo'}).json()['mode']=='tool_error'
    assert not c.get(f'/api/appointments?organization_id={org}').json()

def test_question_definitions_reject_duplicates_and_incomplete_choices(workspace):
    c,_,org,sid,_=workspace
    for questions in [[QUESTIONS[0],QUESTIONS[0]],[{'id':'bad','label':'Scegli','type':'choice','options':['Uno']}],[{'id':'bad','label':' ','type':'text'}]]:
        assert configure(c,org,sid,questions).status_code==422

def test_ambiguous_request_asks_owner_catalogue_and_details_come_from_owner(workspace,monkeypatch):
    c,_,org,sid,_=workspace;configure(c,org,sid)
    mock_http(monkeypatch,lambda request:httpx.Response(200,json={'message':{'tool_calls':[{'function':{'name':'ask_details','arguments':{'needed':['service']}}}]}}))
    result=c.post('/api/chat',json={'organization_id':org,'message':'Vorrei un appuntamento'}).json()
    assert result['mode']=='clarification' and 'Tavolo ristorante' in result['reply']
    result=c.post('/api/chat',json={'organization_id':org,'message':'Mi dai dettagli sulla cena?'}).json()
    assert result['mode']=='tool' and 'Menu alla carta' in result['reply']

def test_web_turns_are_idempotent_and_cannot_impersonate_external_customers(workspace,monkeypatch):
    c,main,org,sid,_=workspace;calls=proposal_mock(monkeypatch,sid)
    body={'organization_id':org,'message':REQUEST};headers={'Idempotency-Key':'unique-request-0001'}
    first=c.post('/api/chat',json=body,headers=headers).json()
    assert c.post('/api/chat',json=body,headers=headers).json()==first and len(calls)==1
    assert c.post('/api/chat',json={**body,'message':'Altro'},headers=headers).status_code==409
    with main.database(write=True) as db:
        cid=db.execute("INSERT INTO conversations(organization_id,channel,external_id,updated_at) VALUES (?,'whatsapp','foreign',1)",(org,)).lastrowid
    assert c.post('/api/chat',json={**body,'conversation_id':cid}).status_code==404

def test_shared_service_alias_requires_clarification_before_inference(workspace,monkeypatch):
    c,_,org,sid,_=workspace
    c.put(f'/api/services/{sid}',json={'organization_id':org,'name':'Visita cardiologica','duration_minutes':30,'aliases':['visita']})
    c.post('/api/services',json={'organization_id':org,'name':'Visita dermatologica','duration_minutes':30,'aliases':['visita']})
    def forbidden(request):raise AssertionError('Ambiguous service must be clarified before inference')
    mock_http(monkeypatch,forbidden)
    result=c.post('/api/chat',json={'organization_id':org,'message':'Vorrei prenotare una visita il 1 settembre 2027 alle 10, a nome Anna'}).json()
    assert result['mode']=='clarification' and result['needed']==['service']
    assert 'Visita cardiologica' in result['reply'] and 'Visita dermatologica' in result['reply']
    assert not c.get(f'/api/appointments?organization_id={org}').json()

def test_concurrent_messages_do_not_interleave_the_same_conversation(workspace):
    _,main,org,_,_=workspace
    from app.chat_sessions import web_turn
    from app.assistant import Chat
    from fastapi import HTTPException
    import pytest
    with main.database() as db:uid=db.execute('SELECT user_id FROM memberships WHERE organization_id=?',(org,)).fetchone()['user_id']
    async def exercise():
        started,finish=asyncio.Event(),asyncio.Event()
        async def responder(*args,**kwargs):
            started.set();await finish.wait()
            return {'mode':'tool','reply':'Ricevuto'}
        data=Chat(organization_id=org,message='Primo')
        first=asyncio.create_task(web_turn(main.database,data,uid,'first-request-0001',responder))
        await started.wait()
        with pytest.raises(HTTPException) as error:await web_turn(main.database,data,uid,'second-request-0002',responder)
        assert error.value.status_code==409
        finish.set();await first
    asyncio.run(exercise())
