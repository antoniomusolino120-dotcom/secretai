# SecretAI — architettura obiettivo

## Vincoli
- Nessuna integrazione Supabase, nessun accesso a progetti FindMyInk.
- SQLite e dashboard attuali sono una demo locale **senza autenticazione**.
- Non esporre pubblicamente l'applicazione.

## Moduli da implementare
1. Identity: account, organizzazioni, ruoli, sessioni, audit.
2. Conversations: inbox, identità canale, handoff a operatore.
3. AI orchestration: prompt per tenant, strumenti con autorizzazione e conferma.
4. Booking: servizi, disponibilità, fusi orari, idempotenza, lock, calendario esterno come fonte di verità.
5. Channels: WhatsApp Cloud API, Instagram Messaging API, SIP/voice worker persistente.
6. Browser teaching: sessione autorizzata, recorder, skill versionate, validazione, retry controllati.
7. Billing: abbonamenti, quote di utilizzo, riconciliazione.

## Requisiti di rilascio
- Auth e isolamento dati dimostrato con test negativi.
- Credenziali cifrate e segregate; segreti solo lato server.
- Google Calendar OAuth e conferma reale della prenotazione.
- Monitoraggio, backup e restore provati.
- Consenso, retention e policy GDPR.
- Test E2E e limiti di utilizzo.

## Priorità immediata
Sostituire la demo con backend autenticato e database dedicato indipendente, senza usare Supabase.
