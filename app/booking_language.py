"""Resolve explicit Italian booking facts; model arguments cannot supply missing facts."""
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

def plain(value): return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))
MONTHS=['gennaio','febbraio','marzo','aprile','maggio','giugno','luglio','agosto','settembre','ottobre','novembre','dicembre']
NUMBERS=dict(zip(['zero','uno','una','due','tre','quattro','cinque','sei','sette','otto','nove','dieci','undici','dodici','tredici','quattordici','quindici','sedici','diciassette','diciotto','diciannove'],[0,1,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19]))
for tens,stem in [(20,'venti'),(30,'trenta'),(40,'quaranta'),(50,'cinquanta'),(60,'sessanta'),(70,'settanta'),(80,'ottanta'),(90,'novanta')]:
    NUMBERS[stem]=tens
    for unit,word in enumerate(['uno','due','tre','quattro','cinque','sei','sette','otto','nove'],1):NUMBERS[(stem[:-1] if unit in (1,8) else stem)+word]=tens+unit
NUMBER_PATTERN='|'.join(sorted(NUMBERS,key=len,reverse=True))

def facts(utterances,timezone):
    now=datetime.now(ZoneInfo(timezone));day=None;clock=None;name=None
    for body in utterances:
        text=plain(body);candidate=None
        try:
            m=re.search(r'\b(20\d{2})-(\d{2})-(\d{2})(?!\d)',text)
            if m:candidate=date(*map(int,m.groups()))
            m=re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b',text)
            if m:candidate=date(int(m[3] or now.year),int(m[2]),int(m[1]))
            m=re.search(r'\b(\d{1,2}|primo|'+NUMBER_PATTERN+r')\s+('+'|'.join(MONTHS)+r')(?:\s+(20\d{2}|duemila[a-z]*))?\b',text)
            if m:
                number=int(m[1]) if m[1].isdigit() else 1 if m[1]=='primo' else NUMBERS[m[1]]
                year=int(m[3]) if m[3] and m[3].isdigit() else 2000+NUMBERS[m[3][7:]] if m[3] and m[3]!='duemila' else 2000 if m[3] else now.year
                candidate=date(year,MONTHS.index(m[2])+1,number)
                if not m[3] and candidate<now.date():candidate=candidate.replace(year=now.year+1)
            if 'dopodomani' in text:candidate=now.date()+timedelta(days=2)
            elif re.search(r'\bdomani\b',text):candidate=now.date()+timedelta(days=1)
            elif re.search(r'\boggi\b',text):candidate=now.date()
            if candidate is None:
                for weekday,label in enumerate(['lunedi','martedi','mercoledi','giovedi','venerdi','sabato','domenica']):
                    if re.search(r'\b'+label+r'\b',text):candidate=now.date()+timedelta(days=(weekday-now.weekday())%7 or 7)
            if candidate:day=candidate
        except (ValueError,KeyError):day=None
        m=re.search(r'\b(?:alle|ore)\s+(\d{1,2}|'+NUMBER_PATTERN+r')\b(?:[:.]([0-5]\d)|\s+e\s+(mezza|un quarto))?',text)
        if m:
            hour=int(m[1]) if m[1].isdigit() else NUMBERS[m[1]];minute=int(m[2]) if m[2] else 30 if m[3]=='mezza' else 15 if m[3] else 0
            if any(v in text for v in ['pomeriggio','sera']) and 1<=hour<12:hour+=12
            clock=time(hour,minute) if 0<=hour<24 else None
        elif (m:=re.search(r'(?<!\d)([0-2]?\d):([0-5]\d)(?!\d)',text)):
            if int(m[1])<24:clock=time(int(m[1]),int(m[2]))
        m=re.search(r'\b(?:mi chiamo|a nome)\s+([^.,!?;\n]+)',body,re.I)
        if m:
            value=re.split(r'\s+(?:per|il giorno|domani|alle)\s+',m[1],maxsplit=1,flags=re.I)[0].strip()
            if value and len(value)<=120:name=value
    return {'day':day,'time':clock,'has_day':day is not None,'has_time':clock is not None,'customer':name}

def grounded_proposal(args,utterances,timezone,selected_service=None):
    data=facts(utterances,timezone);missing=[];name=data['customer'];suggested=args.get('customer')
    if not data['has_day']:missing.append('day')
    if not data['has_time']:missing.append('time')
    if not name and isinstance(suggested,str) and any(plain(v).strip(' .!?')==plain(suggested) for v in utterances):
        if not selected_service or plain(suggested) not in [plain(v) for v in [selected_service['name'],*selected_service['aliases']]]:name=suggested
    if not name:missing.append('customer')
    result={**args,'customer':name}
    if selected_service:result['service_id']=selected_service['id']
    if data['day'] and data['time']:result['starts_at']=datetime.combine(data['day'],data['time'],ZoneInfo(timezone)).isoformat()
    return result,missing
