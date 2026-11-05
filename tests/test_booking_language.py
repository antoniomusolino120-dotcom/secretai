import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.booking_language import facts, grounded_proposal
from test_adapters import mock_http


@pytest.mark.parametrize('message,day,hour,minute', [
    ('Il primo settembre 2027 alle dieci del mattino, a nome Anna Verdi.', '2027-09-01', 10, 0),
    ('Il due settembre duemilaventisette alle undici, mi chiamo Luca.', '2027-09-02', 11, 0),
    ('Il 12/09/2027 alle tre del pomeriggio', '2027-09-12', 15, 0),
    ('Il 2027-09-01 alle 10:30', '2027-09-01', 10, 30),
    ('Il ventuno settembre duemilatrenta alle dieci e mezza', '2030-09-21', 10, 30),
])
def test_explicit_italian_dates_are_grounded(message, day, hour, minute):
    data = facts([message], 'Europe/Rome')
    assert str(data['day']) == day
    assert (data['time'].hour, data['time'].minute) == (hour, minute)


def test_relative_dates_use_company_timezone_and_do_not_trust_model_inventions():
    utterances = ['Vorrei una pulizia del viso', 'Domani alle undici del mattino. Mi chiamo Luca.']
    original = {'service_id': 9, 'customer': 'Inventato', 'starts_at': '2030-01-01T00:00:00Z'}
    result, missing = grounded_proposal(original, utterances, 'Europe/Rome')
    assert not missing
    start = datetime.fromisoformat(result['starts_at'])
    assert start.date() == datetime.now(ZoneInfo('Europe/Rome')).date()+timedelta(days=1)
    assert start.hour == 11 and result['customer'] == 'Luca'


def test_model_cannot_propose_guessed_name_day_or_time(workspace, monkeypatch):
    c, _, org, service, _ = workspace
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={'message': {'tool_calls': [{'function': {'name': 'propose_booking', 'arguments': {
        'service_id': service, 'customer': 'user', 'starts_at': '2027-09-01T10:00:00+02:00'}}}]}}))
    result = c.post('/api/chat', json={'organization_id': org, 'message': 'Vorrei prenotare'}).json()
    assert result['mode'] == 'clarification'
    assert set(result['needed']) == {'day', 'time', 'customer'}
    assert not c.get(f'/api/appointments?organization_id={org}').json()


def test_incomplete_known_service_asks_details_without_calling_model(workspace, monkeypatch):
    c, _, org, service, _ = workspace
    def forbidden(request): raise AssertionError('No inference needed for missing booking facts')
    mock_http(monkeypatch, forbidden)
    result = c.post('/api/chat', json={'organization_id': org, 'message': 'Vorrei prenotare una Consulenza'}).json()
    assert result['mode'] == 'clarification' and set(result['needed']) == {'day', 'time', 'customer'}
