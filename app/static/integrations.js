'use strict';
Object.assign(pages,{voice:['Telefonia','☎'],automations:['Gestionali','⌘']});
state.browser=null;state.browserSelector='';state.procedures=[];
views.connections=async()=>{const i=await api('integrations?'+orgQuery());return `<section class="card"><div class="card-head"><h2>Collega la tua attività</h2></div><div class="connection"><h3>Google Calendar</h3><p class="settings-copy">${i.google.connected?'Collegato: eventi e modifiche si sincronizzano automaticamente.':'Autorizza Google per consultare e gestire la tua agenda.'}</p>${i.google.connected?action('Seleziona calendari','google-calendars')+action('Sincronizza ora','google-sync','','text')+action('Scollega','google-disconnect','','text danger'):action('Collega Google','google-connect')}</div>${['whatsapp','instagram'].map(p=>`<div class="connection"><h3>${p==='whatsapp'?'WhatsApp Business':'Instagram'}</h3><p class="settings-copy">${i.meta.channels.some(c=>c.provider===p)?'Account collegato.':'Autorizza il tuo account aziendale tramite Meta.'}</p>${i.meta.channels.some(c=>c.provider===p)?action('Scollega','meta-disconnect',p,'text danger'):(p==='whatsapp'&&Number(state.org)===2?action('Collega numero di prova','whatsapp-test-connect',p):action('Collega account','meta-oauth',p)+action('Configurazione assistita','meta-connect',p,'text'))}</div>`).join('')}<div class="connection"><h3>Telefono e gestionali</h3><p class="settings-copy">Configura una linea e insegna alla segretaria le procedure della tua attività.</p>${action('Configura telefonia','navigate','voice')}${action('Apri gestionali','navigate','automations')}</div></section>`};
views.voice=async()=>{const [routes,calls]=await Promise.all([api('voice/routes?'+orgQuery()),api('voice/calls?'+orgQuery())]);state.voiceRoutes=routes;return `<div class="columns"><section class="card"><div class="card-head"><h2>Le tue linee telefoniche</h2>${action('+ Nuova linea','voice-new')}</div><p class="settings-copy">Ogni linea collega il tuo numero alla segretaria. Premi 0 durante una chiamata per richiedere un operatore.</p>${routes.map(r=>`<div class="connection"><div class="card-head"><h3>${esc(r.name)}</h3>${badge(r.enabled?'confirmed':'pending')}</div><p class="subtext">${esc(r.greeting)}</p><p class="code">ID collegamento: ${esc(r.id)}</p>${action('Modifica','voice-edit',r.id,'text')}</div>`).join('')||empty('Configura la tua prima linea.')}<p class="subtext">L’attivazione sul numero richiede il collegamento SIP e il collaudo con il provider scelto.</p></section><section class="card"><h2>Ultime chiamate</h2>${calls.map(c=>`<div class="list-row"><div><strong>${fmt(c.created_at*1000)}</strong><small>${c.seconds} secondi</small></div>${badge(c.status)}</div>`).join('')||empty('Nessuna chiamata ricevuta.')}</section></div>`};
views.automations=async()=>{if(state.browser){const b=state.browser;return `<section class="browser-window"><div class="card-head"><h2>Mostra la procedura alla segretaria</h2>${action('Chiudi sessione','browser-close')}</div><div class="browser-controls">${action(b.recording?'Ricomincia registrazione':'Inizia registrazione dopo l’accesso','browser-record')}<label>Azione sull’immagine<select id="browser-mode"><option value="inspect" ${state.browserMode!=='click'?'selected':''}>Seleziona un campo o un risultato</option><option value="click" ${state.browserMode==='click'?'selected':''}>Esegui e registra un clic</option></select></label>${action('Aggiorna immagine','browser-refresh','','text')}</div><p class="hint">${esc(b.url)} · ${b.steps.length} passaggi registrati</p><img class="browser-image" id="browser-screen" src="${esc(b.image)}" alt="Sessione del tuo gestionale, clicca per mostrare un passaggio"><form id="browser-action-form" class="compact-form"><label>Operazione<select name="action"><option value="fill">Compila il campo selezionato</option><option value="select">Scegli un valore</option><option value="assert_text">Verifica il testo del risultato</option><option value="capture">Leggi il riferimento della prenotazione</option></select></label><label>Dato da compilare o leggere<select name="parameter">${[['customer','Nome cliente'],['phone','Telefono'],['email','Email'],['starts_at','Inizio appuntamento'],['ends_at','Fine appuntamento'],['service','Servizio'],['booking_reference','Riferimento prenotazione']].concat(state.services.flatMap(s=>JSON.parse(s.intake_questions_json||'[]').map(q=>['intake_'+q.id,q.label]))).map(([k,l])=>`<option value="${k}">${l}</option>`).join('')}</select></label><label>Formato del campo<select name="format"><option value="text">Testo</option><option value="date">Data: anno-mese-giorno</option><option value="date_it">Data: giorno/mese/anno</option><option value="time">Ora e minuti</option><option value="datetime_local">Data e ora</option></select></label>${field('Valore per questa dimostrazione','value','','password')}<button>Esegui passaggio</button></form><p class="subtext">I valori compilati diventano parametri: password e dati della dimostrazione non vengono salvati nella procedura. Per leggere il riferimento scegli il dato Riferimento prenotazione. Termina sempre con una verifica del risultato.</p>${action('Salva dimostrazione','browser-save')}</section>`}const [procedures,runs]=await Promise.all([api('browser/procedures?'+orgQuery()),api('browser/runs?'+orgQuery())]);state.procedures=procedures;return `<section class="card simple-booking-setup"><h2>Dove gestisci gli appuntamenti?</h2><p class="settings-copy">Collega il calendario o il gestionale che usi già.</p><div class="booking-choices"><button type="button" data-action="booking-google" class="booking-choice"><span class="choice-icon">G</span><span><strong>Google Calendar</strong><small>Collega il tuo calendario</small></span><span aria-hidden="true">›</span></button><button type="button" data-action="procedure-new" class="booking-choice"><span class="choice-icon">▦</span><span><strong>Un altro gestionale</strong><small>Configuralo con una guida</small></span><span aria-hidden="true">›</span></button></div>${procedures.length?`<div class="booking-existing"><h3>Gestionali configurati</h3>${procedures.map(p=>`<div class="connection"><strong>${esc(p.name)}</strong><p class="subtext">${p.approved?'Procedura approvata, da testare':'Configurazione da completare'}</p>${action('Continua configurazione','browser-teach',p.id)}</div>`).join('')}</div>`:''}</section>`};
const originalServiceEdit=actions['service-edit'];actions['service-edit']=id=>{originalServiceEdit(id);const form=$('#service-form');const service=state.services.find(s=>s.id===Number(id));form.dataset.automation=service?.automation_json||'{}'};
Object.assign(actions,{
 'google-sync':async()=>{await send('google/synchronize?'+orgQuery());notify('Sincronizzazione richiesta')},
 'voice-new':()=>actions['voice-edit'](''),
 'voice-edit':id=>{const r=state.voiceRoutes.find(r=>r.id===id)||{};dialog('Configura linea',`<form id="voice-form" data-id="${esc(id)}">${field('Nome della linea','name',r.name||'','text',true)}${field('Operatore di destinazione (PJSIP/...)','transfer_channel',r.transfer_channel||'')}${textfield('Saluto iniziale','greeting',r.greeting||'Sono SecretAI, la segretaria virtuale. Come posso aiutarti?')}<label><input type="checkbox" name="enabled" ${r.enabled?'checked':''}>Abilita questa linea</label><button>Salva linea</button></form>`)},
 'booking-google':()=>actions['google-connect'](),
 'procedure-new':()=>dialog('Aggiungi il gestionale',`<form id="procedure-form">${field('Nome della procedura','name','','text',true)}${field('Indirizzo del gestionale (es. https://gestionale.it)','origin','','url',true)}<p class="subtext">Il dominio deve essere autorizzato nella configurazione del tuo ambiente.</p><button>Crea procedura</button></form>`),
 'browser-teach':async pid=>{state.browser=await send(`browser/procedures/${pid}/teach?${orgQuery()}`);state.browserSelector='';await render()},
 'browser-record':async()=>{state.browser={...state.browser,...await send(`browser/sessions/${state.browser.id}/action?${orgQuery()}`,{action:'record'})};await render()},
 'browser-refresh':async()=>{state.browser={...state.browser,...await api(`browser/sessions/${state.browser.id}?${orgQuery()}`)};await render()},
 'browser-close':async()=>{await api(`browser/sessions/${state.browser.id}?${orgQuery()}`,{method:'DELETE'});state.browser=null;await render()},
 'browser-save':async()=>{await send(`browser/sessions/${state.browser.id}/save?${orgQuery()}`);await actions['browser-close']();notify('Procedura salvata: controlla i passaggi e approva la versione')},
 'procedure-approve':async pid=>{await send(`browser/procedures/${pid}/approve?${orgQuery()}`);await render()},
 'procedure-run':pid=>{const p=state.procedures.find(p=>p.id===pid),names=[...new Set([...p.steps_json.matchAll(/\$\{([A-Za-z0-9_]+)\}/g)].map(m=>m[1]))];dialog('Prova la procedura',`<form id="browser-run-form" data-id="${pid}"><p class="warning-copy">Questa prova esegue le azioni sul gestionale collegato. Usa dati di prova.</p>${names.map(n=>field(n,n,'','password',true)).join('')}<button>Esegui procedura</button></form>`)},
 'browser-resolve':rid=>dialog('Verifica l’esito sul gestionale',`<form id="browser-resolution-form" data-id="${rid}"><p class="settings-copy">Apri il gestionale e controlla l’operazione prima di proseguire. SecretAI non la ripeterà automaticamente.</p><label>Esito verificato<select name="outcome"><option value="verified">Operazione eseguita correttamente</option><option value="not_executed">Operazione non eseguita</option></select></label>${field('Cosa hai verificato','evidence','','text',true)}${field('Riferimento della prenotazione, se presente','booking_reference')}<button>Conferma verifica manuale</button></form>`),
 'whatsapp-test-connect':async()=>{await send('meta/test-whatsapp/connect?'+orgQuery(),{});notify('Numero WhatsApp di prova collegato');await render()},
 'meta-oauth':async provider=>{if(provider==='whatsapp'&&Number(state.org)===2){await actions['whatsapp-test-connect']();return}if(provider==='instagram'){const r=await send(`meta/oauth/${provider}/start?${orgQuery()}`);location.assign(r.authorization_url);return}await prepareWhatsApp();dialog('Collega WhatsApp',`<form id="whatsapp-signup-form"><div style="display:flex;align-items:center;gap:14px;margin:8px 0 22px"><div style="width:52px;height:52px;border-radius:16px;background:#e8f9ee;display:grid;place-items:center;flex-shrink:0"><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#19a864" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 11.5a8.5 8.5 0 0 1-12.7 7.4L3 20l1.2-4.6a8.5 8.5 0 1 1 16.3-3.9Z"/><path d="M8.8 8.5c-.5.4-.6 1.2-.2 2.1.8 1.8 2.3 3.2 4.1 4 .9.4 1.7.3 2.1-.2l.5-.8-2.2-1.1-.8.8c-1.1-.5-1.9-1.3-2.4-2.4l.8-.8-1.1-2.2-.8.6Z"/></svg></div><div><strong style="display:block;font-size:16px">WhatsApp Business</strong><span style="display:block;color:#737987;font-size:13px;margin-top:3px">Collegamento sicuro tramite Meta</span></div></div><p class="subtext" style="margin-bottom:22px">Accedi con Meta per scegliere il numero WhatsApp da collegare a SecretAI. Non dovrai copiare token o codici.</p><button type="submit" style="width:100%;min-height:48px;border-radius:14px">Continua con Meta</button></form>`)},
});
async function prepareWhatsApp(){const config=await send('meta/oauth/whatsapp/start?'+orgQuery());if(!window.FB){await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='https://connect.facebook.net/it_IT/sdk.js';script.onload=resolve;script.onerror=()=>reject(Error('Impossibile caricare Meta'));document.head.append(script)})}window.FB.init({appId:config.app_id,version:config.version||'v27.0',cookie:false,xfbml:false});config.extras={feature:'whatsapp_embedded_signup',version:3,sessionInfoVersion:3,...config.extras};state.whatsappConfig=config}
function startWhatsApp(pin){
 const config=state.whatsappConfig;
 if(!window.FB||!config)throw Error('Riapri il collegamento Meta');
 let code=null,assets=null,completed=false,loginReturned=false;
 const button=document.querySelector('#whatsapp-signup-form button[type="submit"]');
 const setStatus=(message,error=false)=>{
  const form=document.querySelector('#whatsapp-signup-form');
  if(!form)return;
  let hint=form.querySelector('[data-meta-help]');
  if(!hint){hint=document.createElement('p');hint.dataset.metaHelp='1';hint.className='subtext';hint.style.marginTop='12px';form.append(hint)}
  hint.textContent=message;hint.style.color=error?'#b33':'';
 };
 const restore=()=>{if(button?.isConnected){button.disabled=false;button.textContent='Riprova con Meta';button.removeAttribute('aria-busy')}};
 const waiting=(message)=>{if(button?.isConnected){button.disabled=true;button.textContent='◌  In attesa di Meta…';button.setAttribute('aria-busy','true')}setStatus(message)};
 const listener=event=>{
  if(!['https://www.facebook.com','https://web.facebook.com'].includes(event.origin))return;
  let data;try{data=typeof event.data==='string'?JSON.parse(event.data):event.data}catch{return}
  if(data?.type!=='WA_EMBEDDED_SIGNUP')return;
  if(data.event==='FINISH'||data.event==='FINISH_ONLY_WABA'||data.event==='FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING'){
   const next=data.data||{};
   assets={waba_id:String(next.waba_id||next.whatsapp_business_account_id||''),phone_number_id:String(next.phone_number_id||next.phone_id||'')};
   if(!assets.phone_number_id){setStatus('Meta ha autorizzato l’account WhatsApp, ma non ha selezionato un numero. Completa anche il passaggio relativo al numero su Meta.',true);restore()}
   finish();
  }else if(data.event==='CANCEL'||data.event==='ERROR'){
   setStatus('Meta non ha completato la selezione del numero WhatsApp. Riprova e termina tutti i passaggi.',true);
   restore();
  }
 };
 const cleanup=()=>window.removeEventListener('message',listener);
 async function finish(){
  if(completed||!code||!assets)return;
  if(!/^[0-9]+$/.test(assets.waba_id)||!/^[0-9]+$/.test(assets.phone_number_id)){
   setStatus('Meta ha autorizzato l’accesso, ma non ha restituito un numero WhatsApp valido. Completa la selezione del numero su Meta.',true);restore();return;
  }
  completed=true;cleanup();
  waiting('Autorizzazione ricevuta. Verifica del numero WhatsApp in corso…');
  try{
   await send('meta/oauth/whatsapp/complete',{state:config.state,code,waba_id:assets.waba_id,phone_number_id:assets.phone_number_id,pin:pin||''});
   notify('WhatsApp collegato');
   const modal=document.querySelector('#dialog');if(modal?.open)modal.close();
   await render();
  }catch(error){
   setStatus('Meta ha autorizzato l’accesso, ma SecretAI non ha completato il collegamento: '+(error.message||'errore sconosciuto')+'. Riprova il collegamento.',true);
   restore();notify(error.message||'Collegamento WhatsApp non completato',true);
  }
 }
 window.addEventListener('message',listener);
 waiting('Apertura di Meta in corso. Completa la procedura nella finestra di Meta…');
 setTimeout(()=>{if(!completed){cleanup();restore();if(code&&!assets)setStatus('Autorizzazione ricevuta, ma Meta non ha restituito i dati del numero. Riapri il collegamento e seleziona il numero.',true)}},120000);
 window.FB.login(response=>{
  loginReturned=true;
  code=response?.authResponse?.code||null;
  if(code){waiting('Autorizzazione ricevuta. Attendo i dati del numero WhatsApp da Meta…');finish()}
  else{restore();setStatus('Accesso Meta non completato. Controlla la finestra di Meta e riprova.',true)}
 },{config_id:config.config_id,response_type:'code',override_default_response_type:true,extras:config.extras});
}

document.addEventListener('click',event=>{if(event.target.id!=='browser-screen')return;const rect=event.target.getBoundingClientRect(),mode=$('#browser-mode').value;task(async()=>{const result=await send(`browser/sessions/${state.browser.id}/action?${orgQuery()}`,{action:mode,x:Math.floor((event.clientX-rect.left)*1280/rect.width),y:Math.floor((event.clientY-rect.top)*900/rect.height)});if(result.selector)state.browserSelector=result.selector;state.browser={...state.browser,...result};await render()})});
document.addEventListener('submit',event=>{const form=event.target,handlers={
 'voice-form':async d=>{await send('voice/routes'+(form.dataset.id?'/'+form.dataset.id:'')+'?'+orgQuery(),{name:d.get('name'),transfer_channel:d.get('transfer_channel'),greeting:d.get('greeting'),enabled:d.has('enabled')},form.dataset.id?'PUT':'POST')},
 'procedure-form':async d=>{await send('browser/procedures?'+orgQuery(),Object.fromEntries(d))},
 'browser-action-form':async d=>{const result=await send(`browser/sessions/${state.browser.id}/action?${orgQuery()}`,{...Object.fromEntries(d),selector:state.browserSelector});state.browser={...state.browser,...result}},
 'browser-run-form':async d=>{await send(`browser/procedures/${form.dataset.id}/run?${orgQuery()}`,{variables:Object.fromEntries(d),idempotency_key:requestKey(form)})},
 'automation-binding-form':async d=>{const s=state.services.find(s=>s.id===Number(d.get('service_id'))),automation={};for(const op of ['create','reschedule','cancel'])if(d.get(op))automation[op]=d.get(op);await send('services/'+s.id,{organization_id:state.org,name:s.name,duration_minutes:s.duration_minutes,price_cents:s.price_cents,active:Boolean(s.active),automation,description:s.description||'',aliases:JSON.parse(s.aliases_json||'[]'),intake_questions:JSON.parse(s.intake_questions_json||'[]')},'PUT')},
 'browser-resolution-form':async d=>{await send(`browser/runs/${form.dataset.id}/resolve?${orgQuery()}`,Object.fromEntries(d))},
 'whatsapp-signup-form':async d=>{await startWhatsApp(d.get('pin'))},
};if(!handlers[form.id])return;event.preventDefault();if(form.id==='whatsapp-signup-form'){const button=form.querySelector('button[type="submit"]');if(button?.disabled)return;if(button){button.disabled=true;button.textContent='Apertura di Meta…'}try{startWhatsApp(null)}catch(error){if(button){button.disabled=false;button.textContent='Riprova con Meta'}notify(error.message||'Impossibile avviare Meta',true)}return}task(async()=>{await handlers[form.id](new FormData(form));if($('#dialog').open)$('#dialog').close();await render()})});

document.addEventListener('change',event=>{if(event.target.id==='browser-mode')state.browserMode=event.target.value});
