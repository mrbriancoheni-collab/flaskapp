import re
from app import db
from app.models import Account, User

def fake_send_email(to, subject, html):
    m = re.search(r'href="([^"]+/verify/[^"]+)"', html)
    fake_send_email.last_link = m.group(1) if m else None
    return True

def test_register_requires_strong_password(app, client, monkeypatch):
    monkeypatch.setattr("app.auth.email_utils.send_email", fake_send_email)
    r = client.post("/register", data={"email":"u@example.com","password":"weakpass"})
    assert r.status_code == 400
    assert b"at least 12 characters" in r.data

def test_register_sends_verification_and_blocks_login(app, client, monkeypatch):
    monkeypatch.setattr("app.auth.email_utils.send_email", fake_send_email)
    r = client.post("/register", data={"email":"u2@example.com","password":"GoodPass!1234"})
    assert r.status_code in (302, 303)
    assert fake_send_email.last_link

    r = client.post("/login", data={"email":"u2@example.com","password":"GoodPass!1234"}, follow_redirects=True)
    assert b"verify your email" in r.data.lower()

def test_verification_redirects_to_account(app, client, monkeypatch):
    monkeypatch.setattr("app.auth.email_utils.send_email", fake_send_email)
    client.post("/register", data={"email":"u3@example.com","password":"GreatPass!1234"})
    verify_url = fake_send_email.last_link
    r = client.get(verify_url, follow_redirects=True)
    assert b"Email verified" in r.data
    assert b"Your Account" in r.data
