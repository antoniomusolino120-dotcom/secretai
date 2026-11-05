# Stato: dashboard di controllo e preparazione alle integrazioni

## Dashboard concordata con il titolare

La pagina Controllo mostra soltanto interruttori e orari delle risposte per canale, scelta dello strumento di prenotazione e due sezioni inizialmente chiuse: Appuntamenti e Attività. Non propone una seconda agenda, una rubrica CRM o gestione manuale delle prenotazioni. Servizi e domande e Impostazioni IA restano accessibili per configurare la segretaria.

Gli interruttori sono applicati dal backend a chat, ingressi Meta, worker, invio delle risposte automatiche e telefonia. Fasce anche notturne, giorni della settimana, tutto il giorno e fuso dell’attività sono indipendenti dagli orari prenotabili. OFF conserva le credenziali; i lavori della precedente configurazione non ripartono dopo OFF/ON. Email è indicata come non disponibile, senza simulare un collegamento.

La scelta Google Calendar o altro strumento è conservata e applicata alle nuove prenotazioni. Le prenotazioni già create mantengono la destinazione originaria. La scelta di una destinazione non ancora collegata non può produrre una prenotazione locale spacciata per sincronizzata.

La fase corrente resta il collaudo sui soli account del titolare. Apertura commerciale, collegamento autonomo degli account di altre aziende e Stripe sono successivi. Vedere `DASHBOARD_CONTROLS.md` per comportamento e limiti.


## Personalizzazione aggiunta

Il proprietario può configurare tipi di appuntamento, descrizioni, nomi alternativi e domande preliminari per servizio. Le risposte obbligatorie vengono verificate dal backend e salvate negli appuntamenti; la dashboard espone configurazione e dettagli. Le ambiguità note nel catalogo richiedono una scelta e gli argomenti del modello non possono aggiungere nome, giorno o ora mancanti. La chat mantiene cronologia e operazioni idempotenti. Consultare `PERSONALIZZAZIONE.md` e il rapporto di verifica aggiornato.

La priorità resta il funzionamento interno, poi l'apertura ad altre attività, infine la commercializzazione. Questa modifica non attiva servizi a pagamento né certifica la telefonia completa o collegamenti esterni reali.

La preparazione comprende ora anche i moduli mancanti di telefonia e Computer Use. Non equivale al collaudo commerciale su account reali: quel passaggio richiede autorizzazioni, numero SIP, gestionale e infrastruttura scelti dal titolare.

| Area | Lavoro preparatorio implementato | Passaggio con accesso reale |
| --- | --- | --- |
| Backend | PostgreSQL, migrazioni, ruoli, sessioni/CSRF, outbox, concorrenza, idempotenza e audit | Creare l’ambiente dedicato autorizzato e applicare la configurazione |
| Dashboard | Controllo canali/orari, destinazione calendario, storici Appuntamenti e Attività, configurazione servizi/domande e procedure guidate | Inserire i dati aziendali di prova e validare i flussi |
| AI | Servizi/knowledge base, disponibilità, proposte/conferma, spostamento/cancellazione, identificazione cliente e handoff | Eseguire la preparazione automatica del modello sul server scelto e validare conversazioni reali |
| Google | OAuth/PKCE, token cifrato/rinnovo, più calendari, eventi, sincronizzazione incrementale, watch/rinnovo e conflitti | Credenziali Google Cloud, consenso e calendario di prova |
| WhatsApp | Embedded Signup, verifica appartenenza WABA/numero, registrazione/subscription, webhook firmato, inbox, risposte e ricevute | App Meta/configurazione approvata, account Business e numero idoneo |
| Instagram | OAuth nativo, token lungo/rinnovo, subscription, webhook, inbox, risposte e revoca | App Instagram, account professionale e autorizzazione |
| Telefonia | Runtime AudioSocket, Whisper/Piper locali, voce italiana, VAD/barge-in, trascrizioni, consumi, handoff, AGI/dialplan Asterisk e configurazione SIP | Provider/numero/SIP, ACL del provider, operatore di destinazione e chiamata reale |
| Computer Use | Browser isolato, domini autorizzati, login separato dalla registrazione, input parametrizzati, formati data/ora, versioni approvate, replay, verifica/cattura riferimento, collegamento ai servizi e recupero umano | Gestionale di prova, accesso e dimostrazione della procedura reale |
| Stripe | Checkout/Portal, webhook, riconciliazione periodica, rinnovi/insoluti/downgrade/cancellazioni e quote | Account/sandbox, prezzi/limiti e prove di pagamento autorizzate |
| Operazioni | API/worker/browser/voice separati, heartbeat/health, backup cifrato/restore, import SQLite→PostgreSQL, retention configurabile ed export/anonimizzazione | Hosting approvato, dominio, SMTP, policy di conservazione/privacy e collaudo staging |

## Prove e limiti

Il rapporto `VERIFICATION.md` riporta le prove eseguite e distingue provider simulati, browser locale reale e motori vocali reali. I test non autorizzano una dichiarazione di go-live.

La qualità della voce, i tempi sul server scelto, le autorizzazioni effettive Meta/Google, la rete SIP/NAT e la stabilità del gestionale vanno validati durante le integrazioni. Il browser non aggira MFA o CAPTCHA. Un’operazione esterna dall’esito incerto resta sospesa e richiede una verifica, senza replay automatico che potrebbe duplicare una prenotazione.

Non sono stati usati o modificati Supabase, FindMyInk, account reali, numeri telefonici acquistati o infrastrutture a pagamento.
