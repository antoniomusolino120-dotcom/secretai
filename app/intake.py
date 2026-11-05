"""Owner-defined pre-booking questions, checked on every booking channel."""
import json
import re
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictInt, StrictFloat, model_validator

Answers = dict[str, StrictStr | StrictInt | StrictFloat | None]


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
    label: str = Field(min_length=1, max_length=300)
    type: Literal['text', 'number', 'choice'] = 'text'
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def valid(self):
        self.label = self.label.strip()
        self.options = [v.strip() for v in self.options]
        if not self.label or any(not v or len(v)>150 for v in self.options):
            raise ValueError('Inserisci una domanda e opzioni non vuote')
        if len(set(self.options)) != len(self.options): raise ValueError('Le opzioni devono essere diverse')
        if self.type == 'choice' and len(self.options)<2: raise ValueError('Inserisci almeno due opzioni')
        if self.type != 'choice' and self.options: raise ValueError('Le opzioni si applicano alle domande a scelta')
        return self


def service_questions(db, org, sid):
    row = db.execute('SELECT intake_questions_json FROM services WHERE id=? AND organization_id=? AND active=1', (sid, org)).fetchone()
    if not row: raise HTTPException(404, 'Servizio inesistente')
    return json.loads(row['intake_questions_json'])


def validate_answers(questions, answers, complete=True):
    known = {q['id']: q for q in questions}
    if set(answers)-set(known): raise HTTPException(422, 'Risposta riferita a una domanda non presente nel servizio')
    snapshot, missing = [], []
    for key, q in known.items():
        value = answers.get(key)
        if value is None or isinstance(value,str) and not value.strip():
            if q['required']: missing.append(q)
            continue
        if isinstance(value,bool) or not isinstance(value,(str,int,float)): raise HTTPException(422, 'Risposta non valida: '+q['label'])
        text = str(value).strip()
        if len(text)>2000: raise HTTPException(422, 'Risposta troppo lunga: '+q['label'])
        if q['type']=='number':
            text = re.sub(r'^(?:siamo in|siamo|in|per)\s+', '', text.rstrip('.!?').casefold())
            text = re.sub(r'\s+persone$', '', text)
            words = dict(zip(['zero','uno','una','due','tre','quattro','cinque','sei','sette','otto','nove','dieci'],[0,1,1,2,3,4,5,6,7,8,9,10]))
            text = str(words.get(text,text))
            if not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:[.,][0-9]{1,2})?',text): raise HTTPException(422,'Inserisci un numero valido: '+q['label'])
            number=float(text.replace(',','.'));value=int(number) if number.is_integer() else number
        elif q['type']=='choice':
            matches=[v for v in q['options'] if v.casefold()==text.rstrip('.!?').casefold()]
            if not matches: raise HTTPException(422,'Scegli una delle opzioni: '+q['label'])
            value=matches[0]
        else: value=text
        snapshot.append({'id':key,'label':q['label'],'type':q['type'],'answer':value})
    if complete and missing: raise HTTPException(422,'Rispondi alle domande obbligatorie: '+'; '.join(q['label'] for q in missing))
    return snapshot, missing


def scope_for(cid, uid): return f'conversation:{cid}' if cid else f'user:{uid}'


def collect(db, org, args, cid=None, uid=None):
    """Persist a typed draft; return the next owner question or None."""
    questions=service_questions(db,org,args.service_id)
    validate_answers(questions,args.intake_answers,complete=False)
    missing=[q for q in questions if q['id'] not in args.intake_answers or q['required'] and args.intake_answers[q['id']] in (None,'')]
    scope=scope_for(cid,uid)
    if not missing:
        db.execute('DELETE FROM booking_intake_drafts WHERE organization_id=? AND scope=?',(org,scope));return None
    import time
    db.execute('INSERT INTO booking_intake_drafts(organization_id,scope,payload_json,questions_json,expires_at) VALUES (?,?,?,?,?) ON CONFLICT(organization_id,scope) DO UPDATE SET payload_json=excluded.payload_json,questions_json=excluded.questions_json,expires_at=excluded.expires_at',
               (org,scope,args.model_dump_json(),json.dumps(questions),int(time.time())+1800))
    if cid: db.execute('UPDATE booking_proposals SET expires_at=0 WHERE organization_id=? AND conversation_id=? AND result_json IS NULL',(org,cid))
    q=missing[0];text=q['label']
    if q['type']=='choice': text+=' Opzioni: '+', '.join(q['options'])+'.'
    if not q['required']: text+=' Puoi rispondere «salta».'
    return {'mode':'intake','reply':text,'question_id':q['id']}
