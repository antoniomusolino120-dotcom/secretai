"""Local E2E: browser -> API -> database -> displayed result, desktop and mobile.

Only disposable local identities are used. No external accounts or messages.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent


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
                    page.get_by_role("button", name="Crea un account", exact=True).click()
                    expect(page.locator("#app")).to_be_visible()
                    page.get_by_role("button", name="Crea azienda", exact=True).click()
                    page.locator('#org-form input[name="name"]').fill("Studio di prova")
                    page.locator('#org-form button').click()
                    expect(page.locator("#organization")).to_have_value("1" if index == 0 else "2")
                    page.locator('nav [data-id="services"]').click()
                    page.get_by_role("button", name="＋ Nuovo servizio").click()
                    page.locator('#service-form input[name="name"]').fill("Consulenza")
                    page.locator('#service-form input[name="duration_minutes"]').fill("30")
                    page.locator('#service-form input[name="price"]').fill("39")
                    page.locator('#service-form button').click()
                    expect(page.locator('#view')).to_contain_text('Consulenza')
                    page.locator('nav [data-id="appointments"]').click()
                    page.get_by_role("button", name="＋ Nuovo appuntamento").click()
                    page.locator('#appointment-form input[name="customer"]').fill("Cliente dimostrativo")
                    page.locator('#appointment-form input[name="starts_at"]').fill("2027-09-01T10:00")
                    page.locator('#appointment-form button').click()
                    expect(page.locator('#view')).to_contain_text('Cliente dimostrativo')
                    expect(page.locator('#view')).to_contain_text('Confermato')
                    # Refresh proves the cookie session and real persisted data survive.
                    page.reload()
                    expect(page.locator('#view')).to_contain_text('Cliente dimostrativo')
                    page.get_by_role("button", name="Cancella", exact=True).click()
                    page.locator('#cancel-form button').click()
                    expect(page.locator('#view')).to_contain_text('Nessun appuntamento')
                    for section in ("overview", "inbox", "contacts", "assistant", "connections", "billing", "activity", "voice", "automations"):
                        page.locator(f'nav [data-id="{section}"]').click()
                        expect(page.locator('#page-title')).not_to_be_empty()
                        expect(page.locator('#view')).not_to_have_class('loading')
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Horizontal overflow in {section}"
                        if section == "overview" and os.getenv("SECRET_AI_SMOKE_SCREENSHOTS") == "1":
                            (ROOT / "test-results").mkdir(exist_ok=True)
                            page.screenshot(path=str(ROOT / "test-results" / f"dashboard-{index}.png"), full_page=True)
                    assert not errors, errors
                    context.close()
                browser.close()
            print("Browser E2E passed: desktop + mobile, registration, company, service, booking, reload, cancellation, navigation")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    run()
