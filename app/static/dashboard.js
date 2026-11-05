'use strict';
const channelNames={whatsapp:'WhatsApp',instagram:'Instagram',voice:'Telefono',email:'Email',web:'Chat di prova'};
const dayNames=['Lun','Mar','Mer','Gio','Ven','Sab','Dom'];
state.openHistory=new Set();
const previousNavigate=navigate;
navigate=async page=>{state.openHistory.clear();await previousNavigate(['overview','services','appointments','inbox','assistant','voice','automations'].includes(page)?page:'overview');window.scrollTo(0,0)};
const controlPath=()=>`organizations/${state.org}/automation`;

function channelRow(channel,p){
 const active=Boolean(p.enabled&&p.connected),unavailable=!p.available;
 const status=unavailable?'In arrivo':!p.connected?'Da collegare':!active?'Disattivato':p.responding?'Attivo':'Attivo · fuori orario';
 return `<article class="channel-control compact-channel ${active?'is-enabled':''}" data-channel="${channel}"><div class="channel-identity">${channelLogo(channel)}<div><h3>${channelNames[channel]}</h3><p class="channel-status ${active?'is-live':''}">${status}</p></div></div><div class="channel-actions">${unavailable?'<span class="coming-soon">Presto disponibile</span>':active?`<button class="channel-configure" type="button" data-action="channel-configure" data-id="${channel}" aria-label="Configura ${channelNames[channel]}">${uiIcon('settings')}<span>Configura</span></button><button class="channel-power is-on" type="button" role="switch" aria-checked="true" aria-label="Risposte automatiche ${channelNames[channel]}" data-action="channel-toggle" data-id="${channel}">${uiIcon('power')}<span>Spegni</span></button>`:`<button class="channel-activate" type="button" data-action="channel-configure" data-id="${channel}" aria-label="Attiva ${channelNames[channel]}">${uiIcon('power')}<span>Attiva</span></button>`}</div></article>`;
}

function channelConfiguration(channel,p){
 const connected=p.connected,active=Boolean(p.enabled&&connected);
 const link=channel==='web'?'':channel==='voice'?action('Collega la linea telefonica','channel-connect',channel):action(connected?'Gestisci account':'Collega '+channelNames[channel],'channel-connect',channel);
 return `<div class="channel-setup"><div class="setup-identity">${channelLogo(channel)}<div><strong>${channelNames[channel]}</strong><p>${connected?'Collegato': 'Collega il tuo account per attivare le risposte.'}</p></div></div>${link?`<div class="setup-connection">${link}</div>`:''}<form class="channel-schedule" data-channel="${channel}" data-config="true"><h3>Quando deve rispondere?</h3><label class="all-day"><input type="checkbox" name="all_day" ${p.all_day?'checked':''}>Tutto il giorno</label><div class="time-window" ${p.all_day?'hidden':''}>${field('Dalle','start_time',p.start_time,'time',true)}${field('Alle','end_time',p.end_time,'time',true)}</div><fieldset class="weekdays"><legend>Giorni</legend>${dayNames.map((d,i)=>`<label><input type="checkbox" name="day" value="${i}" ${p.days.includes(i)?'checked':''}><span>${d}</span></label>`).join('')}</fieldset><p class="subtext">${!p.all_day&&p.start_time>p.end_time?'La fascia termina il giorno successivo. ':''}Fuso orario: ${esc(state.automation.timezone)}</p>${!connected?'<p class="setup-hint">Puoi salvare gli orari. Le risposte resteranno spente finché non colleghi l’account e le attivi.</p>':''}<button type="submit" class="setup-submit">${connected?active?'Salva modifiche':'Attiva risposte':'Salva orari'}</button></form></div>`;
}
actions['channel-configure']=channel=>{
 const p=state.automation.channels[channel];if(!p?.available)return;
 dialog((p.enabled&&p.connected?'Configura ':'Attiva ')+channelNames[channel],channelConfiguration(channel,p));
};
actions['channel-connect']=async channel=>{
 $('#dialog').close();
 if(channel==='voice')return navigate('voice');
 if(state.automation.channels[channel].connected)return actions['channel-manage'](channel);
 return actions['meta-oauth'](channel);
};

function calendarChoice(integrations){
 const target=state.automation.calendar_target;
 return `<section class="card calendar-choice" aria-labelledby="calendar-title"><div class="card-head"><div><h2 id="calendar-title">Dove gestisci gli appuntamenti?</h2><p class="subtext">SecretAI lavora nel calendario che usi già.</p></div></div><div class="calendar-options">${[['google','Google Calendar','Collega Google e scegli il calendario dove inserire gli appuntamenti.'],['browser','Uso un altro strumento','Mostra con una registrazione guidata come usi l’agenda del tuo gestionale.']].map(([id,title,description])=>`<button class="calendar-option ${target===id?'selected':''}" data-action="calendar-target" data-id="${id}" aria-pressed="${target===id}">${channelLogo(id==='google'?'googlecalendar':'browser')}<strong>${title}</strong><small>${description}</small></button>`).join('')}</div>${target==='auto'?'<p class="subtext">Scegli lo strumento da usare per le nuove prenotazioni.</p>':target==='google'?`<div class="calendar-next"><span>${integrations.google.connected?'Google collegato':'Google da collegare'}</span>${integrations.google.connected?action('Scegli calendario','google-calendars')+action('Scollega Google','google-disconnect','','text danger'):action('Collega Google Calendar','google-connect')}</div>`:`<div class="calendar-next"><p class="subtext">Accedi al tuo gestionale, registra la procedura, verifica il risultato e associala ai tipi di appuntamento. Ogni procedura deve essere collaudata sullo strumento effettivo.</p>${action('Registra la procedura','navigate','automations')}</div>`}</section>`;
}

views.overview=async()=>{
 const i=await api('integrations?'+orgQuery());
 // Reloads preserve expanded sections only during this visit, never across login.
 setTimeout(()=>{for(const key of state.openHistory){const element=document.querySelector(`[data-history="${key}"]`);if(element)element.open=true}},0);
 return `<section class="control-intro"><h2>La tua segretaria, dove vuoi.</h2><p>Attiva un canale per collegarlo e scegliere gli orari.</p></section><section class="channel-grid" aria-label="Canali e orari delle risposte automatiche">${['whatsapp','instagram','voice','email'].map(channel=>channelRow(channel,state.automation.channels[channel])).join('')}</section>${calendarChoice(i)}`;
};

function appointmentHistory(rows){
 return rows.length?`<div class="table-wrap"><table><thead><tr><th>CLIENTE</th><th>APPUNTAMENTO</th><th>QUANDO</th><th>ESITO</th><th></th></tr></thead><tbody>${rows.map(a=>`<tr><td>${esc(a.customer)}</td><td>${esc(a.service)}<small>${a.destination==='google'?'Google Calendar':a.destination==='browser'?'Gestionale collegato':'Prova interna'}</small></td><td>${fmt(a.starts_at)}</td><td>${badge(a.status)}<small>${esc(badges[a.sync_status]||a.sync_status)}</small></td><td>${action('Dettagli','appointment-details',a.id,'text')}</td></tr>`).join('')}</tbody></table></div>`:empty('Nessun appuntamento fissato dall’IA.','Qui comparirà lo storico; gli impegni restano nel tuo calendario.');
}

function activityHistory(threads){
 return threads.length?threads.map(t=>`<details class="activity-thread" data-thread="${t.id}"><summary><span><strong>${esc(t.customer||(t.channel==='web'?'Chat di prova':t.channel==='voice'?'Telefonata':t.external_id||'Cliente'))}</strong><small>${esc(channelNames[t.channel]||t.channel)} · ${fmt(t.updated_at*1000)}</small><span class="thread-preview">${esc(t.last_message||'Nessun messaggio')}</span></span><span aria-hidden="true">⌄</span></summary><div class="thread-history"></div></details>`).join(''):empty('Nessuna attività.','Le conversazioni dei canali collegati compariranno qui.');
}

async function loadHistory(details){
 const id=details.dataset.history,body=details.querySelector('.history-body'),org=state.org;
 body.innerHTML='<p class="subtext" role="status">Caricamento…</p>';
 try{
  if(id==='appointments'){
   const rows=await api('appointments?'+orgQuery()+'&include_cancelled=true&ai_only=true');
   if(org!==state.org||!details.isConnected)return;
   state.appointments=rows;body.innerHTML=appointmentHistory(rows);
  }else{
   const threads=await api('conversations?'+orgQuery());
   if(org!==state.org||!details.isConnected)return;
   state.threads=threads;body.innerHTML=activityHistory(threads);
  }
 }catch(e){body.textContent=e.message}
}

document.addEventListener('toggle',event=>{
 const details=event.target;if(!(details instanceof HTMLDetailsElement))return;
 if(details.dataset.history){if(details.open){state.openHistory.add(details.dataset.history);loadHistory(details)}else state.openHistory.delete(details.dataset.history)}
 if(details.dataset.thread&&details.open&&!details.dataset.loaded){
  details.dataset.loaded='1';const body=details.querySelector('.thread-history'),org=state.org;
  body.innerHTML='<p class="subtext">Caricamento…</p>';
  Promise.all([api(`conversations/${details.dataset.thread}/messages?${orgQuery()}`),api(`conversations/${details.dataset.thread}/operations?${orgQuery()}`)]).then(([messages,operations])=>{
   if(org!==state.org||!details.isConnected)return;
   const thread=state.threads.find(t=>t.id===Number(details.dataset.thread));
   body.innerHTML=`${thread?.status==='human'&&thread.channel!=='voice'?`<div class="card-head"><p class="subtext">Questa conversazione attende un operatore.</p>${action('Riattiva IA','handoff-ai',thread.id,'text')}</div>`:''}${operations.length?`<div class="operation-list"><h4>Operazioni dell’IA</h4>${operations.map(o=>`<p>${esc(o.label)} · riferimento ${esc(o.appointment_id)}</p>`).join('')}</div>`:''}<div class="messages">${messages.map(m=>`<div class="bubble ${m.direction==='outbound'?'out':''}"><small>${m.direction==='inbound'?'Cliente':'Risposta'} · ${fmt(m.created_at*1000)}</small>${esc(m.body)}</div>`).join('')||empty('Nessun messaggio.')}</div>`;
  }).catch(e=>{delete details.dataset.loaded;body.textContent=e.message});
 }
},true);

function scheduleValue(form,enabled){return {enabled,all_day:form.elements.all_day.checked,start_time:form.elements.start_time.value,end_time:form.elements.end_time.value,days:[...form.querySelectorAll('[name=day]:checked')].map(e=>Number(e.value))}}
actions['channel-toggle']=async channel=>{
 const p=state.automation.channels[channel];
 // Toggle only the saved policy; unsaved schedule edits cannot change its meaning.
 await send(controlPath()+'/'+channel,{enabled:!p.enabled,all_day:Boolean(p.all_day),start_time:p.start_time,end_time:p.end_time,days:p.days},'PUT');
 await render();notify(p.enabled?'Risposte automatiche disattivate':'Risposte automatiche attivate');
};
actions['channel-manage']=channel=>dialog('Collegamento '+channelNames[channel],`<p>Puoi spegnere le risposte dalla pagina principale e riaccenderle senza ripetere l’accesso.</p>${action('Scollega account','channel-disconnect',channel,'secondary danger')}`);
actions['channel-disconnect']=async channel=>{await actions['meta-disconnect'](channel);$('#dialog').close()};
actions['calendar-target']=async target=>{await send(`organizations/${state.org}/calendar-target`,{target},'PUT');await render();notify('Scelta salvata per i nuovi appuntamenti')};
actions['auth-register']=()=>{const form=$('#auth-form');form.querySelector('[name=mode]').value='register';form.querySelector('[name=mode]').innerHTML='Registrati <span>↗</span>';form.querySelector('[name=password]').autocomplete='new-password';form.querySelector('[data-action=auth-register]').outerHTML='<button type="button" class="text" data-action="auth-login">Hai già un account? Accedi</button>';$('#auth .muted').textContent='Crea il tuo account aziendale.'};
actions['auth-login']=()=>{const form=$('#auth-form');form.querySelector('[name=mode]').value='login';form.querySelector('[name=mode]').innerHTML='Accedi <span>↗</span>';form.querySelector('[name=password]').autocomplete='current-password';form.querySelector('[data-action=auth-login]').outerHTML='<button type="button" class="text" data-action="auth-register">Non hai un account? Registrati</button>';$('#auth .muted').textContent='Accedi al controllo della tua segretaria.'};

document.addEventListener('change',event=>{if(event.target.name==='all_day')event.target.closest('form').querySelector('.time-window').hidden=event.target.checked});
document.addEventListener('submit',event=>{
 const form=event.target;if(!form.matches('.channel-schedule'))return;event.preventDefault();
 task(async()=>{const channel=form.dataset.channel;await send(controlPath()+'/'+channel,scheduleValue(form,Boolean(state.automation.channels[channel].connected)),'PUT');$('#dialog').close();await render();notify('Configurazione salvata')});
});

// Read-only summaries have their own navigation tabs; the control page stays focused.
views.appointments=async()=>{
 state.appointments=await api('appointments?'+orgQuery()+'&include_cancelled=true&ai_only=true');
 return `<section class="card"><div class="card-head"><div><h2>Appuntamenti</h2><p class="subtext">Gli appuntamenti fissati dall’IA nel tuo calendario.</p></div></div>${appointmentHistory(state.appointments)}</section>`;
};
views.inbox=async()=>{
 state.threads=await api('conversations?'+orgQuery());
 return `<section class="card"><div class="card-head"><div><h2>Attività</h2><p class="subtext">Conversazioni e operazioni dell’IA, divise per cliente e canale.</p></div></div>${activityHistory(state.threads)}</section>`;
};
