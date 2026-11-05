"""Local E2E: browser -> API -> database -> displayed result, desktop and mobile.

Only disposable local identities are used. No external accounts or messages.
"""
import os
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.db import make_database
from app.assistant import propose, confirm, Proposal


def run():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as directory:
        env = {**os.environ, "SECRET_AI_ENV": "development", "SECRET_AI_PUBLIC_URL": base,
               "SECRET_AI_DB": str(Path(directory)/"smoke.sqlite3"), "SECRET_AI_BILLING_REQUIRED": "0"}
        env.pop("SECRET_AI_DATABASE_URL", None)
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("API did not start")
                try:
                    urllib.request.urlopen(base+"/health/ready", timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
                for index, viewport in enumerate([{"width": 1440, "height": 1000}, {"width": 390, "height": 844}]):
                    context = browser.new_context(viewport=viewport)
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(base)
                    page.locator('#auth-form input[name="email"]').fill(f"smoke{index}@example.com")
                    page.locator('#auth-form input[name="password"]').fill("smoke-test-password-123")
                    page.get_by_role('button', name='Registrati', exact=True).click()
                    page.locator('#auth-form button[type=submit]').click()
                    expect(page.locator("#app")).to_be_visible()
                    page.locator('#org-form input[name="name"]').fill("Studio di prova")
                    page.locator('#org-form button').click()
                    expect(page.locator("#organization")).to_have_value("1" if index == 0 else "2")
                    page.locator('nav [data-id="services"]').click()
                    page.get_by_role("button", name="＋ Nuovo servizio").click()
                    page.locator('#service-form input[name="name"]').fill("Consulenza")
                    page.locator('#service-form input[name="duration_minutes"]').fill("30")
                    page.locator('#service-form input[name="price"]').fill("39")
                    page.locator('#service-form textarea[name="description"]').fill('Colloquio iniziale di prova')
                    page.get_by_role('button',name='+ Aggiungi domanda',exact=True).click()
                    page.locator('[name="question-label"]').fill('Quante persone partecipano?')
                    page.locator('[name="question-type"]').select_option('number')
                    page.locator('#service-form > button').click()
                    expect(page.locator('#view')).to_contain_text('Consulenza')
                    page.locator('nav [data-id="overview"]').click()
                    expect(page.get_by_role('heading',name='La tua segretaria, dove vuoi.')).to_be_visible()
                    expect(page.locator('.channel-grid .compact-channel')).to_have_count(3)
                    expect(page.locator('.channel-schedule')).to_have_count(0)
                    expect(page.get_by_text('Chat di prova',exact=True)).to_have_count(0)
                    expect(page.locator('#nav button')).to_have_count(4)
                    expect(page.locator('.channel-control[data-channel="email"]')).to_have_count(0)
                    page.get_by_role('button',name='Attiva WhatsApp',exact=True).click()
                    schedule=page.locator('.channel-schedule[data-channel="whatsapp"]')
                    schedule.locator('[name="all_day"]').uncheck()
                    schedule.locator('[name="start_time"]').fill('18:00')
                    schedule.locator('[name="end_time"]').fill('09:00')
                    schedule.get_by_role('button',name='Salva orari',exact=True).click()
                    expect(page.locator('#notice')).to_have_text('Configurazione salvata')
                    expect(page.locator('#dialog')).not_to_be_visible()
                    page.reload()
                    page.get_by_role('button',name='Attiva WhatsApp',exact=True).click()
                    expect(page.locator('.channel-schedule [name="all_day"]')).not_to_be_checked()
                    expect(page.locator('.channel-schedule [name="start_time"]')).to_have_value('18:00')
                    expect(page.locator('.channel-schedule [name="end_time"]')).to_have_value('09:00')
                    page.get_by_role('button',name='Chiudi',exact=True).click()
                    org=index+1
                    csrf=page.evaluate('state.csrf')
                    headers={'X-CSRF-Token':csrf}
                    policy={'enabled':False,'all_day':True,'start_time':'18:00','end_time':'09:00','days':list(range(7))}
                    assert page.request.put(base+f'/api/organizations/{org}/automation/web',data=policy,headers=headers).ok
                    blocked=page.request.post(base+'/api/chat',data={'organization_id':org,'message':'ciao'},headers=headers)
                    assert blocked.status==409,blocked.text()
                    policy['enabled']=True
                    assert page.request.put(base+f'/api/organizations/{org}/automation/web',data=policy,headers=headers).ok
                    response=page.request.post(base+'/api/chat',data={'organization_id':org,'message':'ciao'},headers=headers)
                    assert response.ok,response.text()
                    conversation=response.json()['conversation_id']
                    user=page.request.get(base+'/api/auth/me').json()['id']
                    services=page.request.get(base+f'/api/services?organization_id={org}').json()
                    # Seed a confirmed AI proposal through the real booking code;
                    # no model or external account is claimed by this UI smoke test.
                    engine=create_engine('sqlite:///'+str(Path(directory)/'smoke.sqlite3'))
                    database=make_database(engine)
                    proposal=propose(database,org,Proposal(service_id=services[0]['id'],customer='Cliente dimostrativo',starts_at=datetime.fromisoformat('2027-09-01T10:00:00+02:00'),intake_answers={
                        json.loads(services[0]['intake_questions_json'])[0]['id']:3}),conversation,user)
                    confirmed=confirm(database,org,proposal['proposal_id'],conversation,user)
                    engine.dispose()
                    page.locator('nav [data-id="appointments"]').click()
                    expect(page.locator('#view')).to_contain_text('Cliente dimostrativo')
                    expect(page.locator('#view')).to_contain_text('Confermato')
                    assert page.get_by_role('button',name='＋ Nuovo appuntamento').count()==0
                    assert page.get_by_role('button',name='Sposta',exact=True).count()==0
                    page.get_by_role('button',name='Dettagli',exact=True).click()
                    expect(page.locator('#dialog-body')).to_contain_text('Quante persone partecipano?')
                    expect(page.locator('#dialog-body')).to_contain_text('3')
                    page.get_by_role('button',name='Chiudi',exact=True).click()
                    page.locator('nav [data-id="inbox"]').click()
                    page.locator('[data-thread] > summary').first.click()
                    expect(page.locator('.thread-history')).to_contain_text('Operazioni dell’IA')
                    expect(page.locator('.thread-history')).to_contain_text('Prenotazione registrata')
                    # Cancel via the backend only: the dashboard remains a history,
                    # with no competing manual agenda controls.
                    aid=confirmed['appointment']['id']
                    assert page.request.delete(base+f'/api/appointments/{aid}?organization_id={org}',headers=headers).ok
                    page.reload()
                    page.locator('nav [data-id="appointments"]').click()
                    expect(page.locator('#view')).to_contain_text('Cancellato')
                    page.locator('nav [data-id="overview"]').click()
                    page.get_by_role('button',name='Google Calendar',exact=False).filter(has=page.locator('strong',has_text='Google Calendar')).click()
                    expect(page.locator('.calendar-option[data-id="google"]')).to_have_attribute('aria-pressed','true')
                    page.get_by_role('button',name='Uso un altro strumento',exact=False).click()
                    expect(page.locator('.calendar-option[data-id="browser"]')).to_have_attribute('aria-pressed','true')
                    page.get_by_role('button',name='Registra la procedura',exact=True).click()
                    expect(page.locator('#view')).to_contain_text('I tuoi gestionali')
                    for section in ('overview','services','appointments','inbox'):
                        page.locator(f'nav [data-id="{section}"]').click()
                        expect(page.locator('#page-title')).not_to_be_empty()
                        expect(page.locator('#view')).not_to_have_class('loading')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'Horizontal overflow in {section}'
                        if section=='overview' and os.getenv('SECRET_AI_SMOKE_SCREENSHOTS')=='1':
                            (ROOT/'test-results').mkdir(exist_ok=True)
                            page.screenshot(path=str(ROOT/'test-results'/f'dashboard-{index}.png'),full_page=True)
                    assert not errors, errors
                    context.close()
                browser.close()
            print("Browser E2E passed: desktop + mobile, registration, questionnaires, response switches, night schedule persistence, calendar selection, AI appointment/activity histories")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    run()
