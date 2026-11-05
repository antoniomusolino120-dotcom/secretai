"""Response switches: one policy shared by web, messaging workers and calls."""
import json
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth import audit

CHANNELS = ('whatsapp', 'instagram', 'voice', 'email', 'web')
current_policy = ContextVar('secretai_response_policy', default=None)


class ChannelControl(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    all_day: bool = True
    start_time: str = '18:00'
    end_time: str = '09:00'
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)

    @model_validator(mode='after')
    def valid_schedule(self):
        if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', v) for v in (self.start_time, self.end_time)):
            raise ValueError('Usa orari HH:MM')
        if not self.all_day and self.start_time == self.end_time:
            raise ValueError('Per rispondere 24 ore seleziona Tutto il giorno')
        if len(set(self.days)) != len(self.days) or any(d < 0 or d > 6 for d in self.days):
            raise ValueError('Giorni non validi')
        return self


class CalendarTarget(BaseModel):
    target: Literal['google', 'browser']


def policy(db, org_id, channel):
    org = db.execute('SELECT timezone,assistant_enabled FROM organizations WHERE id=?', (org_id,)).fetchone()
    if not org:
        raise HTTPException(404, 'Attività inesistente')
    row = db.execute('SELECT * FROM channel_controls WHERE organization_id=? AND channel=?', (org_id, channel)).fetchone()
    if row:
        return {**dict(row), 'days': json.loads(row['days_json']), 'timezone': org['timezone']}
    # Preserve existing installations until the owner explicitly changes a channel.
    return {'enabled': channel == 'web' or channel != 'email' and bool(org['assistant_enabled']),
            'all_day': True, 'start_time': '18:00', 'end_time': '09:00',
            'days': list(range(7)), 'revision': 0, 'timezone': org['timezone']}


def in_schedule(p, at=None):
    if not p['enabled']:
        return False
    local = datetime.fromtimestamp(time.time() if at is None else at, timezone.utc).astimezone(ZoneInfo(p['timezone']))
    day, clock = local.weekday(), local.strftime('%H:%M')
    if p['all_day']:
        return day in p['days']
    start, end = p['start_time'], p['end_time']
    if start < end:
        return day in p['days'] and start <= clock < end
    # A Monday 18:00–09:00 window ends on Tuesday, even if Tuesday is unchecked.
    return day in p['days'] and clock >= start or (day - 1) % 7 in p['days'] and clock < end


def permitted(db, org_id, channel, revision=None, at=None):
    if channel not in CHANNELS or channel == 'email':
        return False
    p = policy(db, org_id, channel)
    return (revision is None or p['revision'] == revision) and in_schedule(p, at)


def assert_current(db, org_id):
    """Run under the organization write lock, immediately before an AI mutation."""
    value = current_policy.get()
    if value and value[0] == org_id and not permitted(db, org_id, value[1], value[2]):
        raise HTTPException(409, 'Risposte automatiche disattivate o fuori orario')


def connection_state(db, org_id, channel):
    if channel == 'web':
        return True
    if channel == 'email':
        return False
    if channel == 'voice':
        return bool(db.execute('SELECT 1 FROM voice_routes WHERE organization_id=? AND enabled=1', (org_id,)).fetchone())
    return bool(db.execute('''SELECT 1 FROM meta_channels m JOIN channel_credentials c
        ON m.organization_id=c.organization_id AND m.provider=c.provider
        WHERE m.organization_id=? AND m.provider=? AND (c.expires_at IS NULL OR c.expires_at>?)''',
        (org_id, channel, int(time.time()))).fetchone())


def install(database, current_user, require_org):
    router = APIRouter(tags=['response-controls'])

    @router.get('/api/organizations/{organization_id}/automation')
    def controls(organization_id: int, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id)
        with database() as db:
            org = db.execute('SELECT timezone,calendar_target FROM organizations WHERE id=?', (organization_id,)).fetchone()
            channels = {}
            for channel in CHANNELS:
                p = policy(db, organization_id, channel)
                linked = connection_state(db, organization_id, channel)
                channels[channel] = {k: p[k] for k in ('enabled', 'all_day', 'start_time', 'end_time', 'days', 'revision')}
                channels[channel].update(connected=linked, available=channel != 'email', responding=linked and permitted(db, organization_id, channel))
        return {'timezone': org['timezone'], 'calendar_target': org['calendar_target'], 'channels': channels}

    @router.put('/api/organizations/{organization_id}/automation/{channel}')
    def save_control(organization_id: int, channel: str, data: ChannelControl, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        if channel not in CHANNELS:
            raise HTTPException(422, 'Canale non supportato')
        with database(write=True, organization_id=organization_id) as db:
            if data.enabled:
                if not connection_state(db, organization_id, channel):
                    raise HTTPException(409, 'Collega e configura il canale prima di attivarlo')
                if not db.execute('SELECT 1 FROM services WHERE organization_id=? AND active=1', (organization_id,)).fetchone():
                    raise HTTPException(409, 'Configura almeno un tipo di appuntamento attivo')
            db.execute('''INSERT INTO channel_controls(organization_id,channel,enabled,all_day,start_time,end_time,days_json,revision)
                VALUES (?,?,?,?,?,?,?,1) ON CONFLICT(organization_id,channel) DO UPDATE SET
                enabled=excluded.enabled,all_day=excluded.all_day,start_time=excluded.start_time,
                end_time=excluded.end_time,days_json=excluded.days_json,revision=channel_controls.revision+1''',
                (organization_id, channel, int(data.enabled), int(data.all_day), data.start_time, data.end_time, json.dumps(data.days)))
            if not data.enabled and channel == 'voice':
                db.execute("UPDATE voice_calls SET status='human' WHERE organization_id=? AND status IN ('created','active')", (organization_id,))
            audit(db, 'automation.' + channel + '.updated', user_id, organization_id, channel)
        return {'ok': True}

    @router.put('/api/organizations/{organization_id}/calendar-target')
    def save_target(organization_id: int, data: CalendarTarget, user_id: int = Depends(current_user)):
        require_org(user_id, organization_id, owner=True)
        with database(write=True, organization_id=organization_id) as db:
            db.execute('UPDATE organizations SET calendar_target=? WHERE id=?', (data.target, organization_id))
            audit(db, 'calendar.target_updated', user_id, organization_id, data.target)
        return {'ok': True}

    return router
