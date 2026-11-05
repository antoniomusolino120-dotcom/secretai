# Architettura SecretAI

FastAPI espone dashboard/API; PostgreSQL è il database di produzione indipendente. Le migrazioni sono versionate. Autenticazione, sessioni, ruoli, CSRF, audit e vincoli tenant proteggono l’accesso ai dati. Il modello interpreta intenzioni e usa strumenti: non autorizza da solo operazioni, e il suo testo libero non è una conferma.

La transactional outbox collega prenotazioni e operazioni esterne. Gli slot nuovi e precedenti rimangono riservati durante uno spostamento non verificato. Il worker esegue Google/Meta/Stripe e riconcilia periodicamente eventi, abbonamenti e token. I provider dall’esito incerto richiedono verifica umana quando il replay può duplicare un effetto.

La telefonia è un servizio persistente AudioSocket collegato ad Asterisk con AGI autenticato. Whisper e Piper lavorano localmente; l’input vocale interrompe l’output, le trascrizioni entrano nell’inbox e il handoff ritorna al dialplan per il trasferimento. Il Caller ID non è un’identità autenticata per modificare appuntamenti preesistenti.

Il browser worker è separato dall’API. Ogni sessione ha contesto browser e storage cifrato per azienda; gli host sono esplicitamente autorizzati e risolti/pinned. La registrazione inizia dopo il login e conserva azioni parametrizzate, versioni e verifiche, non password della dimostrazione. Le procedure approvate possono essere associate ai servizi per creare, spostare e cancellare nel gestionale. L’appuntamento viene confermato soltanto dopo l’esito verificato del gestionale e dell’eventuale calendario.

Nessun componente usa Supabase o risorse di FindMyInk. Il runbook distingue preparazione applicativa e collaudo live.
