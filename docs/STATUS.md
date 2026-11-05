# Stato: preparazione alle integrazioni

La preparazione comprende ora anche i moduli mancanti di telefonia e Computer Use. Non equivale al collaudo commerciale su account reali: quel passaggio richiede autorizzazioni, numero SIP, gestionale e infrastruttura scelti dal titolare.

| Area | Lavoro preparatorio implementato | Passaggio con accesso reale |
| --- | --- | --- |
| Backend | PostgreSQL, migrazioni, ruoli, sessioni/CSRF, outbox, concorrenza, idempotenza e audit | Creare l’ambiente dedicato autorizzato e applicare la configurazione |
| Dashboard | CRM, inbox, agenda, servizi/prezzi/orari, segretaria, collegamenti, telefonia, dimostrazioni e procedure dei gestionali | Inserire i dati aziendali di prova e validare i flussi |
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
