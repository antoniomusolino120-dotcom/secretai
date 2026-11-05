# Preparazione alle integrazioni

Il codice degli adattatori testuali e di billing è predisposto per un collaudo assistito; il prodotto non è pronto al lancio. Prima configurare credenziali private e usare account di prova dedicati esclusivamente a SecretAI. Non usare risorse di FindMyInk.

- Google: client OAuth Web, redirect `/api/google/callback`, account calendario di prova, consenso. Provare lettura, conflitti, creazione/modifica/cancellazione, retry e revoca token.
- Meta: app approvata, versione API esplicita, webhook `/api/meta/webhook`, chiave firma e verify token. Collegamento assistito tramite dashboard con ID/token verificati; OAuth/Embedded Signup completo ancora da sviluppare.
- Stripe: sandbox dedicata, Prices e limiti approvati, restricted API key, webhook `/api/billing/webhook`. Gli eventi necessari sono elencati in `app/billing.py`. Provare anche insoluti, rinnovi, cancellazioni e rischio; la pagina di successo non concede accesso.
- Email: SMTP con STARTTLS e mittente autorizzato per conferma e recupero password. Non sono state inviate email reali.
- Telefonia/gestionale: richiedono prima l'implementazione dei moduli indicati in `STATUS.md` e successivamente account, numero e gestionale di prova.

Prima di attivare imposte automatiche, vanno concordati prezzi, IVA, registrazioni fiscali e modalità di fatturazione. Nessuna configurazione Stripe Tax viene attivata da questo codice.
