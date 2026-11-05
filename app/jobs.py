"""Transactional outbox with leases and bounded retry.

Handlers with non-idempotent external effects must raise AttentionRequired after
ambiguous responses. A crashed non-replayable send is never sent a second time.
"""
import asyncio
import json
import secrets
import time


class AttentionRequired(Exception):
    pass


def claim(database):
    now = int(time.time())
    with database(write=True) as db:
        # A crash after a Meta send may mean delivery succeeded; do not duplicate.
        db.execute("""UPDATE jobs SET status='attention',last_error='Delivery outcome unknown; operator review required'
            WHERE status='running' AND locked_until<=? AND kind IN ('meta_send','browser_run')""", (now,))
        sql = """SELECT * FROM jobs WHERE (status='pending' AND available_at<=?)
            OR (status='running' AND locked_until<=? AND kind NOT IN ('meta_send','browser_run'))
            ORDER BY id LIMIT 1"""
        if db.dialect == "postgresql":
            sql += " FOR UPDATE SKIP LOCKED"
        row = db.execute(sql, (now, now)).fetchone()
        if not row:
            return None
        token = secrets.token_urlsafe(24)
        db.execute("UPDATE jobs SET status='running',attempts=attempts+1,locked_until=?,lease_token=? WHERE id=?",
                   (now+180, token, row["id"]))
        return {**dict(row), "lease_token": token, "attempts": row["attempts"]+1}


async def run_once(database, handlers):
    job = claim(database)
    if not job:
        return False
    status, error = "done", ""
    try:
        if job["kind"] not in handlers:
            raise AttentionRequired("Handler not configured")
        await asyncio.wait_for(handlers[job["kind"]](job, json.loads(job["payload_json"])), timeout=120)
    except AttentionRequired as exc:
        status, error = "attention", str(exc)[:200]
    except Exception:
        # Exception text can contain credentials or customer data. Store only a code.
        status = "pending" if job["attempts"] < 5 else "failed"
        error = "Provider operation failed; retry scheduled" if status == "pending" else "Retry limit reached"
        if job["kind"] in {"meta_send", "browser_run"}:
            status, error = "attention", "External outcome requires operator review"
    with database(write=True, organization_id=job["organization_id"]) as db:
        db.execute("""UPDATE jobs SET status=?,last_error=?,available_at=?,locked_until=NULL,lease_token=NULL
            WHERE id=? AND lease_token=? AND status='running'""",
            (status, error, int(time.time()) + min(300, 2 ** job["attempts"]), job["id"], job["lease_token"]))
    return True
