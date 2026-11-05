#!/usr/bin/env python3
"""Minimal Asterisk AGI bridge. Secrets stay in the Asterisk process environment."""
import json
import os
import re
import sys
import urllib.request

def agi(command):
    print(command,flush=True)
    return sys.stdin.readline()

def set_variable(name,value):
    if not re.fullmatch(r'[A-Za-z0-9_+@./:-]*',value):value=''
    agi(f'SET VARIABLE {name} "{value}"')

def main():
    # Consume AGI metadata without logging caller identifiers.
    for line in sys.stdin:
        if not line.strip():break
    base=os.getenv('SECRET_AI_API_INTERNAL_URL','http://api:8000').rstrip('/')
    key=os.environ['SECRET_AI_INTERNAL_TOKEN']
    operation=sys.argv[1]
    if operation=='start':
        rid=os.environ['SECRET_AI_VOICE_ROUTE_ID']
        if not re.fullmatch('[a-f0-9]{32}',rid):raise ValueError('Invalid route')
        request=urllib.request.Request(base+'/internal/voice/calls',data=json.dumps({'route_id':rid}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=5) as response:data=json.load(response)
        set_variable('SECRET_AI_CALL_ID',data['call_id'])
    else:
        call_id=sys.argv[2]
        if not re.fullmatch('[a-f0-9-]{36}',call_id):raise ValueError('Invalid call')
        request=urllib.request.Request(base+'/internal/voice/calls/'+call_id,headers={'Authorization':'Bearer '+key})
        with urllib.request.urlopen(request,timeout=5) as response:data=json.load(response)
        set_variable('SECRET_AI_TRANSFER',data['transfer_channel'])

if __name__=='__main__':
    try:main()
    except Exception:
        set_variable('SECRET_AI_CALL_ID' if len(sys.argv)<2 or sys.argv[1]=='start' else 'SECRET_AI_TRANSFER','')
