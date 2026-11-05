"""Stripe Checkout/Portal, signed webhooks and authoritative reconciliation.

No product or price is created automatically. Commercial decisions are supplied
by the operator in SECRET_AI_PLANS_JSON. The success page grants no entitlement.
"""
import json
import os
import secrets
import string
import time
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import audit
from app.booking import enqueue
from app.jobs import AttentionRequired

API_VERSION = "2026-09-30.endive"
LIFECYCLE = {"checkout.session.completed", "checkout.session.async_payment_succeeded",
             "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted",
             "invoice.paid", "invoice.payment_failed"}
RISK = {"charge.dispute.created", "charge.refunded", "radar.early_fraud_warning.created"}


def plans():
    try:
        value = json.loads(os.getenv("SECRET_AI_PLANS_JSON", "{}"))
        for name, plan in value.items():
            if not name or not plan["price_id"].startswith("price_") or int(plan["message_limit"]) < 0 or int(plan["voice_seconds_limit"]) < 0:
                raise ValueError()
        return value
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(503, "Configurazione piani non valida")


def client():
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(503, "Pagamenti non configurati")
    return stripe.StripeClient(key, stripe_version=API_VERSION, max_network_retries=2)


def consume(database, org_id, metric, amount, key):
    if amount <= 0 or metric not in {"messages", "voice_seconds"}:
        raise ValueError("Invalid usage event")
    with database(write=True, organization_id=org_id) as db:
        previous = db.execute("SELECT metric,amount FROM usage_events WHERE organization_id=? AND key=?", (org_id, key)).fetchone()
        if previous:
            if previous["metric"] != metric or previous["amount"] != amount:
                raise HTTPException(409, "Chiave consumo già utilizzata")
            return
        account = db.execute("SELECT * FROM billing_accounts WHERE organization_id=?", (org_id,)).fetchone()
        required = os.getenv("SECRET_AI_BILLING_REQUIRED", "1" if os.getenv("SECRET_AI_ENV") == "production" else "0") == "1"
        now = int(time.time())
        if required and (not account or account["status"] not in {"active", "trialing"} or account["period_end"] <= now or account["risk_review"]):
            raise HTTPException(402, "Abbonamento non attivo o da verificare")
        period = account["period_start"] if account else int(datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
        plan = plans().get(account["plan"]) if account else None
        if required and not plan:
            raise HTTPException(402, "Piano non riconosciuto")
        if plan:
            used = db.execute("SELECT COALESCE(SUM(amount),0) AS n FROM usage_events WHERE organization_id=? AND period_start=? AND metric=?", (org_id, period, metric)).fetchone()["n"]
            if used + amount > int(plan["message_limit" if metric == "messages" else "voice_seconds_limit"]):
                raise HTTPException(402, "Limite di utilizzo raggiunto")
        db.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?)", (org_id, key, metric, amount, period, now))


class Checkout(BaseModel):
    organization_id: int = Field(gt=0)
    plan: str = Field(min_length=1, max_length=80)


def install(database, current_user, require_org):
    router = APIRouter(tags=["billing"])

    @router.get("/api/billing")
    def status(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database() as db:
            row = db.execute("SELECT plan,status,period_start,period_end,cancel_at_period_end,risk_review,updated_at FROM billing_accounts WHERE organization_id=?", (organization_id,)).fetchone()
            usage = [dict(r) for r in db.execute("SELECT metric,SUM(amount) AS used,period_start FROM usage_events WHERE organization_id=? GROUP BY metric,period_start ORDER BY period_start DESC LIMIT 20", (organization_id,))]
        return {"subscription": dict(row) if row else None, "usage": usage,
                "plans": [{"id": name, "message_limit": p["message_limit"], "voice_seconds_limit": p["voice_seconds_limit"]} for name, p in plans().items()]}

    @router.post("/api/billing/checkout")
    def checkout(data: Checkout, user_id: int = Depends(current_user), key: str | None = Header(None, alias="Idempotency-Key")):
        require_org(user_id, data.organization_id, owner=True)
        if not key or not 8 <= len(key) <= 100:
            raise HTTPException(422, "Idempotency-Key richiesta")
        plan = plans().get(data.plan)
        if not plan:
            raise HTTPException(422, "Piano non disponibile")
        api = client()
        base = os.getenv("SECRET_AI_PUBLIC_URL", "http://localhost:8000").rstrip("/")
        with database(write=True, organization_id=data.organization_id) as db:
            row = db.execute("SELECT * FROM billing_accounts WHERE organization_id=?", (data.organization_id,)).fetchone()
            if row and row["stripe_subscription_id"] and row["status"] not in {"canceled", "incomplete_expired"}:
                raise HTTPException(409, "Gestisci l'abbonamento dal portale pagamenti")
            if not row:
                customer = api.v1.customers.create({}, options={"idempotency_key": f"secretai-customer-{data.organization_id}"})
                db.execute("INSERT INTO billing_accounts(organization_id,stripe_customer_id) VALUES (?,?)", (data.organization_id, customer.id))
                customer_id = customer.id
            else:
                customer_id = row["stripe_customer_id"]
        # Stable integration label for retries of the same Checkout request.
        import hashlib
        suffix = "".join(string.ascii_lowercase[b % 26] for b in hashlib.sha256(key.encode()).digest()[:8])
        session = api.v1.checkout.sessions.create({"mode": "subscription", "customer": customer_id,
            "line_items": [{"price": plan["price_id"], "quantity": 1}],
            "success_url": base+"/#billing", "cancel_url": base+"/#billing",
            "integration_identifier": "secretai_"+suffix}, options={"idempotency_key": f"checkout:{data.organization_id}:{key}"})
        return {"url": session.url}

    @router.post("/api/billing/portal")
    def portal(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database() as db:
            row = db.execute("SELECT stripe_customer_id FROM billing_accounts WHERE organization_id=?", (organization_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Nessun account pagamenti")
        session = client().v1.billing_portal.sessions.create({"customer": row["stripe_customer_id"],
                      "return_url": os.getenv("SECRET_AI_PUBLIC_URL", "http://localhost:8000").rstrip("/")+"/#billing"})
        return {"url": session.url}

    @router.post("/api/billing/webhook")
    async def webhook(request: Request, signature: str | None = Header(None, alias="Stripe-Signature")):
        secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(503, "Webhook Stripe non configurato")
        try:
            event = stripe.Webhook.construct_event(await request.body(), signature or "", secret)
        except (ValueError, stripe.SignatureVerificationError):
            raise HTTPException(400, "Firma Stripe non valida")
        event = event.to_dict()
        event_id, kind, obj = event["id"], event["type"], event["data"]["object"]
        with database(write=True) as db:
            if db.execute("SELECT 1 FROM stripe_events WHERE id=?", (event_id,)).fetchone():
                return {"ok": True}
            customer = obj.get("customer")
            # Risk events may reference only a charge; resolve through Stripe's graph.
            if kind in RISK and not customer:
                charge_id = obj.get("charge")
                if charge_id:
                    charge = client().v1.charges.retrieve(charge_id)
                    customer = charge.customer
            account = db.execute("SELECT organization_id FROM billing_accounts WHERE stripe_customer_id=?", (customer,)).fetchone() if isinstance(customer, str) else None
            db.execute("INSERT INTO stripe_events VALUES (?,?,?)", (event_id, kind, int(time.time())))
            if account:
                org_id = account["organization_id"]
                if kind in RISK:
                    db.execute("UPDATE billing_accounts SET risk_review=1 WHERE organization_id=?", (org_id,))
                    audit(db, "billing.risk_review", organization_id=org_id, entity_id=event_id)
                elif kind in LIFECYCLE:
                    enqueue(db, org_id, "stripe_reconcile", {}, "stripe:"+event_id)
        return {"ok": True}
    return router


def handlers(database):
    async def reconcile(job, payload):
        org_id = job["organization_id"]
        api = client()
        with database(write=True, organization_id=org_id) as db:
            row = db.execute("SELECT * FROM billing_accounts WHERE organization_id=?", (org_id,)).fetchone()
            if not row:
                return
            subscriptions = api.v1.subscriptions.list({"customer": row["stripe_customer_id"], "status": "all", "limit": 100})
            live = [s for s in subscriptions.data if s.status not in {"canceled", "incomplete_expired"}]
            if len(live) > 1 or subscriptions.has_more:
                db.execute("UPDATE billing_accounts SET risk_review=1 WHERE organization_id=?", (org_id,))
                return
            subscription = live[0] if live else None
            if not subscription:
                db.execute("UPDATE billing_accounts SET status='canceled',period_end=0,updated_at=? WHERE organization_id=?", (int(time.time()), org_id))
                return
            subscription_data = subscription.to_dict()
            items = subscription_data["items"]["data"]
            if len(items) != 1:
                raise AttentionRequired("Subscription contains an unsupported price configuration")
            item = items[0]
            price_id = item["price"]["id"]
            plan = next((name for name, p in plans().items() if p["price_id"] == price_id), "")
            start, end = item.get("current_period_start", 0), item.get("current_period_end", 0)
            db.execute("""UPDATE billing_accounts SET stripe_subscription_id=?,plan=?,status=?,period_start=?,period_end=?,cancel_at_period_end=?,updated_at=? WHERE organization_id=?""",
                       (subscription.id, plan, subscription.status, start, end, int(subscription.cancel_at_period_end), int(time.time()), org_id))
            audit(db, "billing.reconciled", organization_id=org_id, entity_id=subscription.id)
    return {"stripe_reconcile": reconcile}
