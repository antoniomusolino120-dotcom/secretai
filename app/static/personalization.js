'use strict';
function questionRow(q={}){
 const id=q.id||'q_'+crypto.randomUUID().replaceAll('-','').slice(0,16);
 return `<fieldset class="intake-question" data-question-id="${esc(id)}"><legend>Domanda prima dell’appuntamento</legend><label>Domanda al cliente<input name="question-label" value="${esc(q.label||'')}" maxlength="300" required></label><label>Tipo di risposta<select name="question-type">${[['text','Testo libero'],['number','Numero'],['choice','Scelta tra opzioni']].map(([v,l])=>`<option value="${v}" ${q.type===v?'selected':''}>${l}</option>`).join('')}</select></label><label class="question-options" ${q.type==='choice'?'':'hidden'}>Opzioni, una per riga<textarea name="question-options">${esc((q.options||[]).join('\n'))}</textarea></label><label><input type="checkbox" name="question-required" ${q.required!==false?'checked':''}> Risposta obbligatoria</label><button type="button" class="text danger" data-action="question-remove" data-id="${esc(id)}">Rimuovi domanda</button></fieldset>`;
}
function readQuestions(form){return [...form.querySelectorAll('[data-question-id]')].map(row=>({id:row.dataset.questionId,label:row.querySelector('[name=question-label]').value.trim(),type:row.querySelector('[name=question-type]').value,required:row.querySelector('[name=question-required]').checked,options:row.querySelector('[name=question-type]').value==='choice'?row.querySelector('[name=question-options]').value.split('\n').map(v=>v.trim()).filter(Boolean):[]}))}
const serviceEditor=actions['service-edit'];
actions['service-edit']=id=>{
 serviceEditor(id);const form=$('#service-form'),service=state.services.find(s=>s.id===Number(id))||{};
 const extra=document.createElement('div');extra.innerHTML=`${textfield('Descrizione e dettagli che la segretaria può spiegare','description',service.description||'')}${field('Altri nomi usati dai clienti, separati da virgole','aliases',JSON.parse(service.aliases_json||'[]').join(', '))}<h3>Domande prima dell’appuntamento</h3><p class="subtext">Decidi cosa deve chiedere la segretaria per questo tipo di appuntamento, nell’ordine indicato. Le risposte saranno visibili nell’agenda. Per ricominciare il cliente può dire «ricomincia».</p><div id="intake-questions">${JSON.parse(service.intake_questions_json||'[]').map(questionRow).join('')}</div>${action('+ Aggiungi domanda','question-add')}`;
 form.insertBefore(extra,form.querySelector('button:not([type])'));
};
actions['question-add']=()=>{if(document.querySelectorAll('#intake-questions .intake-question').length>=20)throw Error('Puoi configurare fino a 20 domande per servizio');$('#intake-questions').insertAdjacentHTML('beforeend',questionRow());$('#intake-questions .intake-question:last-child input').focus()};
actions['question-remove']=id=>[...document.querySelectorAll('[data-question-id]')].find(v=>v.dataset.questionId===id)?.remove();
document.addEventListener('change',event=>{
 if(event.target.name==='question-type')event.target.closest('fieldset').querySelector('.question-options').hidden=event.target.value!=='choice';
 if(event.target.closest('#appointment-form')&&event.target.name==='service_id')appointmentQuestions();
});
function appointmentQuestions(){
 const form=$('#appointment-form');if(!form)return;let holder=$('#appointment-intake');
 if(!holder){holder=document.createElement('div');holder.id='appointment-intake';form.insertBefore(holder,form.querySelector('button'))}
 const service=state.services.find(v=>v.id===Number(form.elements.service_id.value));
 holder.innerHTML=JSON.parse(service?.intake_questions_json||'[]').map(q=>`<label>${esc(q.label)}${q.type==='choice'?`<select name="intake-${esc(q.id)}" ${q.required?'required':''}><option value="">Scegli…</option>${q.options.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select>`:`<input name="intake-${esc(q.id)}" type="${q.type==='number'?'number':'text'}" ${q.type==='number'?'min="0" step="any"':''} maxlength="2000" ${q.required?'required':''}>`}</label>`).join('');
}
const appointmentEditor=actions['appointment-new'];actions['appointment-new']=()=>{appointmentEditor();appointmentQuestions()};
actions['appointment-details']=id=>{const a=state.appointments.find(a=>a.id===Number(id));if(!a)return;const answers=JSON.parse(a.intake_json||'[]');dialog('Dettagli dell’appuntamento',`<p><strong>${esc(a.customer)}</strong> · ${esc(a.service)}</p><p>${fmt(a.starts_at)}</p>${answers.length?answers.map(q=>`<div class="connection"><strong>${esc(q.label)}</strong><p>${esc(q.answer)}</p></div>`).join(''):empty('Nessuna risposta aggiuntiva registrata.')}`)};
const assistantView=views.assistant;
views.assistant=async()=>{const history=await api('chat?'+orgQuery());state.chat=history.messages.map(m=>(m.direction==='inbound'?'Tu: ':'SecretAI: ')+m.body);const html=await assistantView();return html.replace('Per spostare o cancellare un appuntamento, usa l’agenda o passa a un operatore.','Puoi prenotare, spostare o cancellare. Le domande dipendono dal servizio scelto. La conversazione viene salvata nell’inbox.')};
