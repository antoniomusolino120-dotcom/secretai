"""Local configuration check. Prints names/status only, never secret values."""
import importlib.util
import json
import os
from pathlib import Path
import sys

def check():
    groups={
      'google':['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI','SECRET_AI_ENCRYPTION_KEY'],
      'whatsapp':['META_APP_ID','META_APP_SECRET','META_VERIFY_TOKEN','META_GRAPH_VERSION','META_WHATSAPP_CONFIG_ID'],
      'instagram':['INSTAGRAM_APP_ID','INSTAGRAM_APP_SECRET','INSTAGRAM_REDIRECT_URI','META_GRAPH_VERSION'],
      'stripe':['STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','SECRET_AI_PLANS_JSON'],
      'browser':['SECRET_AI_INTERNAL_TOKEN','BROWSER_WORKER_URL','BROWSER_ALLOWED_ORIGINS','SECRET_AI_ENCRYPTION_KEY'],
      'voice':['SECRET_AI_INTERNAL_TOKEN','PIPER_MODEL','SECRET_AI_VOICE_ROUTE_ID'],
    }
    result={name:{'implemented':True,'missing_configuration':[key for key in keys if not os.getenv(key)],'live_verified':False} for name,keys in groups.items()}
    if os.getenv('SECRET_AI_PLANS_JSON','{}')=='{}' and 'SECRET_AI_PLANS_JSON' not in result['stripe']['missing_configuration']:result['stripe']['missing_configuration'].append('SECRET_AI_PLANS_JSON')
    result['voice']['tts_model_present']=Path(os.getenv('PIPER_MODEL','__missing__')).is_file()
    result['voice']['stt_installed']=importlib.util.find_spec('faster_whisper') is not None
    result['voice']['tts_installed']=importlib.util.find_spec('piper') is not None
    result['browser']['playwright_installed']=importlib.util.find_spec('playwright') is not None
    return result
if __name__=='__main__':print(json.dumps(check(),indent=2))
