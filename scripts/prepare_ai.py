"""Prepare the configured Ollama model on the selected host, without cloud keys."""
import os,time
import httpx

def main():
    base=os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
    for attempt in range(60):
        try:
            response=httpx.get(base+'/api/tags',timeout=5,trust_env=False);response.raise_for_status();break
        except httpx.HTTPError:
            if attempt==59:raise RuntimeError('Ollama is not available')
            time.sleep(2)
    model=os.getenv('OLLAMA_MODEL','qwen2.5:3b')
    with httpx.Client(timeout=1800,trust_env=False) as client:
        response=client.post(base+'/api/pull',json={'model':model,'stream':False});response.raise_for_status()
        if response.json().get('status')!='success':raise RuntimeError('Model preparation failed')
        # Confirm the configured model supports the operational tools used by SecretAI.
        response=client.post(base+'/api/chat',json={'model':model,'stream':False,'messages':[{'role':'user','content':'Elenca i servizi disponibili usando lo strumento services.'}],'tools':[{'type':'function','function':{'name':'services','description':'Elenca i servizi','parameters':{'type':'object','properties':{}}}}]})
        response.raise_for_status()
        calls=response.json().get('message',{}).get('tool_calls',[])
        if not calls or calls[0].get('function',{}).get('name')!='services':raise RuntimeError('Model tool-calling check failed')
    print('Ollama model downloaded and tool-calling verified')
if __name__=='__main__':main()
