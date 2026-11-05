import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime

import httpx
import pytest

from app.channel_controls import in_schedule
from conftest import outsider
from test_adapters import mock_http


def control(c, org, channel='web', **changes):
    return c.put(f'/api/organizations/{org}/automation/{channel}', json={
        'enabled': True, 'all_day': True, 'start_time': '18:00', 'end_time': '09:00',
        'days': list(range(7)), **changes})


@pytest.mark.parametrize('iso,expected', [
    ('2026-11-02T16:59:59+00:00', False),
    ('2026-11-02T17:00:00+00:00', True),
    ('2026-11-03T07:59:59+00:00', True),
    ('2026-11-03T08:00:00+00:00', False),
    ('2026-11-03T17:00:00+00:00', False),
])
def test_overnight_window_uses_start_day_and_exclusive_end(iso, expected):
    p = {'enabled': True, 'all_day': False, 'start_time': '18:00', 'end_time': '09:00',
         'days': [0], 'timezone': 'Europe/Rome'}
    assert in_schedule(p, datetime.fromisoformat(iso).timestamp()) is expected


def test_schedule_uses_local_clock_on_both_sides_of_dst():
    p = {'enabled': True, 'all_day': False, 'start_time': '02:00', 'end_time': '03:00',
         'days': [6], 'timezone': 'Europe/Rome'}
    for iso in ('2026-10-25T00:30:00Z', '2026-10-25T01:30:00Z'):
        assert in_schedule(p, datetime.fromisoformat(iso).timestamp())
    assert not in_schedule(p, datetime.fromisoformat('2026-10-25T02:00:00Z').timestamp())
    assert not in_schedule({**p, 'enabled': False}, datetime.fromisoformat('2026-10-25T01:30:00Z').timestamp())


def test_owner_can_pause_chat_without_destroying_history_or_other_channels(workspace):
    c, main, org, _, _ = workspace
    assert c.post('/api/chat', json={'organization_id': org, 'message': 'ciao'}).status_code == 200
    before = c.get(f'/api/chat?organization_id={org}').json()
    assert control(c, org, enabled=False).status_code == 200
    assert c.post('/api/chat', json={'organization_id': org, 'message': 'ciao'}).status_code == 409
    assert c.get(f'/api/chat?organization_id={org}').json() == before
    assert control(c, org).status_code == 200
    assert c.post('/api/chat', json={'organization_id': org, 'message': 'ciao'}).json()['reply']
    assert control(c, org, 'whatsapp').status_code == 409
    assert control(c, org, 'email').status_code == 409
    assert control(c, org, start_time='25:00').status_code == 422
    assert control(c, org, all_day=False, start_time='09:00', end_time='09:00').status_code == 422
    assert control(c, org, days=[]).status_code == 422
    assert control(c, org, days=[0, 0]).status_code == 422
    outsider(c)
    assert control(c, org, enabled=False).status_code == 403
    assert c.get(f'/api/organizations/{org}/automation').status_code == 403
    assert c.put(f'/api/organizations/{org}/calendar-target', json={'target': 'google'}).status_code == 403


def test_off_on_during_model_inference_cannot_create_or_send_a_stale_proposal(workspace, monkeypatch):
    c, main, org, sid, _ = workspace
    assert control(c, org).status_code == 200
    def handler(request):
        assert control(c, org, enabled=False).status_code == 200
        assert control(c, org).status_code == 200
        return httpx.Response(200, json={'message': {'tool_calls': [{'function': {
            'name': 'propose_booking', 'arguments': {'service_id': sid, 'customer': 'Anna', 'starts_at': '2027-09-01T10:00:00+02:00'}}}]}})
    mock_http(monkeypatch, handler)
    result = c.post('/api/chat', json={'organization_id': org, 'message': 'Vorrei una consulenza il 1 settembre 2027 alle 10, a nome Anna'}).json()
    assert result['mode'] == 'paused' and not result['reply']
    with main.database() as db:
        assert not db.execute('SELECT 1 FROM booking_proposals WHERE organization_id=?', (org,)).fetchone()
        assert not db.execute("SELECT 1 FROM messages WHERE organization_id=? AND direction='outbound'", (org,)).fetchone()


def test_chat_final_commit_rechecks_policy_even_with_an_inflight_adapter(workspace, monkeypatch):
    from app import assistant
    c, main, org, _, _ = workspace
    async def response(*args, **kwargs):
        assert control(c, org, enabled=False).status_code == 200
        return {'mode': 'tool', 'reply': 'Must not be delivered'}
    monkeypatch.setattr(assistant, 'respond', response)
    result = c.post('/api/chat', json={'organization_id': org, 'message': 'ciao'}).json()
    assert result['mode'] == 'paused' and not result['reply']
    with main.database() as db:
        assert not db.execute("SELECT 1 FROM messages WHERE organization_id=? AND direction='outbound'", (org,)).fetchone()


def test_old_turn_cannot_restart_after_channel_is_reenabled(workspace, monkeypatch):
    from app.assistant import respond
    c, main, org, _, _ = workspace
    assert control(c, org).status_code == 200
    original = c.get(f'/api/organizations/{org}/automation').json()['channels']['web']['revision']
    assert control(c, org, enabled=False).status_code == 200
    assert control(c, org).status_code == 200
    result = asyncio.run(respond(main.database, org, 'ciao', policy_revision=original))
    assert result == {'mode': 'paused', 'reply': ''}


def test_queued_ai_delivery_is_suppressed_after_pause_but_human_reply_is_not(workspace, monkeypatch):
    from app.meta_channels import handlers
    c, main, org, _, _ = workspace
    with main.database(write=True) as db:
        db.execute("UPDATE organizations SET assistant_enabled=1 WHERE id=?", (org,))
        cid = db.execute("INSERT INTO conversations(organization_id,channel,external_id,updated_at) VALUES (?,'whatsapp','client',?)", (org, int(time.time()))).lastrowid
        mid = db.execute("INSERT INTO messages(organization_id,conversation_id,direction,body,created_at,external_id) VALUES (?,?,'outbound','Answer',?,'ai:123')", (org, cid, int(time.time()))).lastrowid
    assert control(c, org, 'whatsapp', enabled=False).status_code == 200
    async def exercise():
        await handlers(main.database)['meta_send']({'organization_id': org}, {'message_id': mid, 'automation_revision': 0})
    asyncio.run(exercise())
    with main.database() as db:
        assert db.execute('SELECT delivery_status FROM messages WHERE id=?', (mid,)).fetchone()['delivery_status'] == 'suppressed'
    # This must not silently drop an explicitly sent human message. Missing channel
    # credentials still raise the ordinary reconnect error.
    with main.database(write=True) as db:
        db.execute("UPDATE messages SET external_id=NULL,delivery_status='pending' WHERE id=?", (mid,))
    from app.jobs import AttentionRequired
    with pytest.raises(AttentionRequired): asyncio.run(exercise())


@pytest.mark.parametrize('channel', ['whatsapp', 'instagram'])
def test_meta_ingress_stays_silent_when_off_and_old_jobs_cannot_restart(workspace, monkeypatch, channel):
    from app import assistant
    c, main, org, _, _ = workspace
    monkeypatch.setenv('META_APP_SECRET', 'test-only-signing-secret')
    with main.database(write=True) as db:
        db.execute('INSERT INTO meta_channels(organization_id,provider,external_id) VALUES (?,?,?)', (org, channel, '12345'))
        db.execute("INSERT INTO channel_credentials(organization_id,provider,token_ciphertext) VALUES (?,?,'test-token')", (org, channel))
    def receive(mid):
        if channel == 'whatsapp':
            payload = {'object': 'whatsapp_business_account', 'entry': [{'changes': [{'value': {
                'metadata': {'phone_number_id': '12345'}, 'messages': [{'id': mid, 'from': '67890', 'type': 'text', 'text': {'body': 'ciao'}}]}}]}]}
        else:
            payload = {'object': 'instagram', 'entry': [{'id': '12345', 'messaging': [{
                'sender': {'id': '67890'}, 'message': {'mid': mid, 'text': 'ciao'}}]}]}
        raw = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'test-only-signing-secret', raw, hashlib.sha256).hexdigest()
        assert c.post('/api/meta/webhook', content=raw, headers={'X-Hub-Signature-256': signature}).status_code == 200
    assert control(c, org, channel, enabled=False).status_code == 200
    receive('off-message')
    with main.database() as db:
        assert not db.execute("SELECT 1 FROM jobs WHERE organization_id=? AND kind='ai_reply'", (org,)).fetchone()
    assert control(c, org, channel).status_code == 200
    receive('queued-message')
    with main.database() as db:
        job = dict(db.execute("SELECT * FROM jobs WHERE organization_id=? AND kind='ai_reply'", (org,)).fetchone())
    assert control(c, org, channel, enabled=False).status_code == 200
    assert control(c, org, channel).status_code == 200
    async def must_not_run(*args, **kwargs): raise AssertionError('Old message reached the model')
    monkeypatch.setattr(assistant, 'respond', must_not_run)
    asyncio.run(assistant.handlers(main.database)['ai_reply'](job, json.loads(job['payload_json'])))
    with main.database() as db:
        assert not db.execute("SELECT 1 FROM messages WHERE organization_id=? AND direction='outbound'", (org,)).fetchone()
        assert db.execute('SELECT token_ciphertext FROM channel_credentials WHERE organization_id=? AND provider=?', (org, channel)).fetchone()['token_ciphertext'] == 'test-token'


def test_phone_control_blocks_provisioning_and_interrupts_existing_calls(workspace, monkeypatch):
    c, main, org, _, _ = workspace
    key = 'private-service-token-with-more-than-32-characters'
    monkeypatch.setenv('SECRET_AI_INTERNAL_TOKEN', key)
    route = c.post(f'/api/voice/routes?organization_id={org}', json={'name': 'Test', 'enabled': True}).json()['id']
    assert control(c, org, 'voice').status_code == 200
    def start(): return c.post('/internal/voice/calls', json={'route_id': route}, headers={'Authorization': 'Bearer ' + key})
    call = start().json()['call_id']
    assert control(c, org, 'voice', enabled=False).status_code == 200
    assert start().status_code == 409
    with main.database() as db:
        assert db.execute('SELECT status FROM voice_calls WHERE id=?', (call,)).fetchone()['status'] == 'human'
        assert db.execute('SELECT enabled FROM voice_routes WHERE id=?', (route,)).fetchone()['enabled'] == 1


def test_calendar_selection_blocks_unconnected_destination_without_local_fallback(workspace):
    c, main, org, sid, _ = workspace
    body = {'organization_id': org, 'service_id': sid, 'customer': 'Anna', 'starts_at': '2027-09-01T10:00:00+02:00'}
    assert c.put(f'/api/organizations/{org}/calendar-target', json={'target': 'google'}).status_code == 200
    assert c.post('/api/appointments', json=body).status_code == 409
    with main.database(write=True) as db:
        db.execute("INSERT INTO google_connections(organization_id,token_ciphertext) VALUES (?,'test-token')", (org,))
    result = c.post('/api/appointments', json=body).json()
    assert result['status'] == 'pending_sync'
    assert c.put(f'/api/organizations/{org}/calendar-target', json={'target': 'browser'}).status_code == 200
    assert c.post('/api/appointments', json={**body, 'starts_at': '2027-09-02T10:00:00+02:00'}).status_code == 409
    # A destination change must not redirect an existing Google appointment.
    with main.database() as db:
        row = db.execute('SELECT destination FROM appointments WHERE id=?', (result['id'],)).fetchone()
        assert row['destination'] == 'google'


def test_activity_operations_and_ai_only_appointments_are_scoped(workspace, monkeypatch):
    from test_personalization import proposal_mock
    c, main, org, sid, _ = workspace
    proposal_mock(monkeypatch, sid)
    body = {'organization_id': org, 'message': 'Vorrei una consulenza il 1 settembre 2027 alle 10, a nome Anna'}
    first = c.post('/api/chat', json=body).json()
    assert first['mode'] == 'proposal'
    result = c.post('/api/chat', json={**body, 'message': 'confermo'}).json()
    assert result['mode'] == 'booking_result'
    rows = c.get(f'/api/appointments?organization_id={org}&ai_only=true&include_cancelled=true').json()
    assert len(rows) == 1 and rows[0]['created_by_ai'] == 1
    ops = c.get(f"/api/conversations/{first['conversation_id']}/operations?organization_id={org}").json()
    assert ops == [{'appointment_id': rows[0]['id'], 'operation': 'create', 'label': 'Prenotazione registrata'}]
    assert c.delete(f"/api/appointments/{rows[0]['id']}?organization_id={org}").status_code == 200
    assert len(c.get(f'/api/appointments?organization_id={org}&ai_only=true&include_cancelled=true').json()) == 1
    outsider(c)
    assert c.get(f"/api/conversations/{first['conversation_id']}/operations?organization_id={org}").status_code == 403
