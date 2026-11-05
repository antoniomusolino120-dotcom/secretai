# Specifica operativa SecretAI

Riferimento: documento di progetto fornito da Antonio il 5 novembre 2026.

## Prodotto

SaaS per professionisti, negozi, studi e aziende: segretaria virtuale 24/7 che risponde a telefono, WhatsApp e Instagram, consulta servizi e istruzioni aziendali e gestisce prenotazioni. Registrazione, configurazione e collegamenti devono essere utilizzabili da clienti senza competenze tecniche.

Ogni azienda deve registrarsi, configurare servizi/prezzi/orari/disponibilità, collegare Google Calendar, WhatsApp Business, Instagram e un numero telefonico, insegnare procedure per gestionali esterni, attivare l'AI e controllare conversazioni, clienti, appuntamenti, statistiche, abbonamento e consumi da un'unica dashboard.

## Architettura e confini

- Dashboard web responsive; backend Python/FastAPI; PostgreSQL indipendente in produzione.
- Modelli AI configurabili, preferenza per soluzioni open source sostenibili.
- STT Whisper/equivalente, TTS Piper/equivalente, telefonia Asterisk/SIP/provider compatibile.
- API ufficiali Meta, Google Calendar OAuth/API, automazioni Playwright apprese per dimostrazione.
- Abbonamenti Stripe, hosting dedicato con HTTPS, backup e monitoraggio.
- Non utilizzare né modificare Supabase. Non utilizzare né modificare FindMyInk.
- Sviluppare autonomamente ogni attività che non richieda credenziali, autorizzazioni, acquisti o decisioni aziendali.
- Chiedere intervento del titolare soltanto quando indispensabile, indicando il passaggio concreto.

## Ordine di realizzazione

1. Fondamenta: API, migrazioni, sicurezza, tenant, dashboard, test.
2. Segretaria testuale: strumenti AI, knowledge base, Calendar, Meta e inbox.
3. Telefonia: flusso audio realtime, STT/TTS, interruzioni e trasferimento.
4. Computer Use: dimostrazioni, procedure versionate, sessioni e verifica esito.
5. Commercializzazione: billing, quote, hosting, monitoraggio e collaudo.

## Interventi riservati al titolare

| Area | Intervento indispensabile |
| --- | --- |
| Meta | App Developers, account Business/Instagram idonei, consenso e verifiche/approvazioni Meta |
| Google | Progetto OAuth, credenziali, calendario di prova e consenso |
| Telefonia | Scelta/attivazione provider, numero e autorizzazione SIP/API |
| Stripe | Account dedicato, sandbox, prezzi/piani/limiti, autorizzazione della configurazione |
| Hosting | Scelta del provider, approvazione dei costi e attivazione produzione |
| Gestionale | Accesso a un ambiente di prova, dimostrazione e validazione della procedura |
| Azienda/privacy | Dati di prova, regole commerciali, trattamento dati e validazione legale |

## Criterio di completamento

Il prodotto è pronto soltanto dopo test reali positivi di conversazione, prenotazione, telefonia, messaggistica, automazione e pagamento. Un file di configurazione, un test con provider simulato o una dashboard non dimostrano il completamento di questi flussi.
