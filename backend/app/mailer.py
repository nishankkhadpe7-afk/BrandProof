"""Transactional email (password reset, invites). First configured provider wins:

1. Gmail API over HTTPS   GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN (scope gmail.send).
                          Works on Render's free plan, which blocks SMTP ports 25/465/587.
2. Resend                 RESEND_API_KEY
3. Gmail SMTP             GMAIL_ADDRESS + GMAIL_APP_PASSWORD (local machines and paid hosts only)
4. none                   emails are written to the server log

MAIL_FROM sets the sender (for Gmail it must be your Gmail address or a verified alias);
APP_URL is the web app address used in links.
"""
import base64
import html
import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

log = logging.getLogger("brandproof.mail")


def app_url() -> str:
    return (os.environ.get("APP_URL") or "http://localhost:3000").rstrip("/")


def provider() -> str | None:
    e = os.environ.get
    if e("GMAIL_CLIENT_ID") and e("GMAIL_CLIENT_SECRET") and e("GMAIL_REFRESH_TOKEN"):
        return "gmail-api"
    if e("RESEND_API_KEY"):
        return "resend"
    if e("GMAIL_ADDRESS") and e("GMAIL_APP_PASSWORD"):
        return "gmail-smtp"
    return None


def enabled() -> bool:
    return provider() is not None


def _mime(to: str, subject: str, html_body: str, text_body: str, sender: str) -> EmailMessage:
    m = EmailMessage()
    m["To"], m["From"], m["Subject"] = to, sender, subject
    m.set_content(text_body)
    m.add_alternative(html_body, subtype="html")
    return m


def _gmail_api(msg: EmailMessage) -> None:
    e = os.environ
    tok = httpx.post("https://oauth2.googleapis.com/token", timeout=15, data={
        "client_id": e["GMAIL_CLIENT_ID"], "client_secret": e["GMAIL_CLIENT_SECRET"],
        "refresh_token": e["GMAIL_REFRESH_TOKEN"], "grant_type": "refresh_token"})
    tok.raise_for_status()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = httpx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", timeout=15,
                   headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, json={"raw": raw})
    r.raise_for_status()


def _gmail_smtp(msg: EmailMessage) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
        s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)


def _layout(title: str, body: str, cta: str, link: str) -> str:
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;color:#15171c">
<p style="font-weight:600;font-size:16px;margin:0 0 20px">BrandProof</p>
<h1 style="font-size:20px;margin:0 0 12px">{html.escape(title)}</h1>
<p style="font-size:15px;line-height:1.55;color:#4b505b">{body}</p>
<p style="margin:24px 0"><a href="{html.escape(link)}" style="background:#15171c;color:#fff;padding:10px 18px;border-radius:9px;text-decoration:none;font-weight:600">{html.escape(cta)}</a></p>
<p style="font-size:12.5px;color:#80858f">Or open this link: {html.escape(link)}</p></div>"""


def send(to: str, subject: str, title: str, body: str, cta: str, link: str) -> bool:
    """Send one email. Returns True if the provider accepted it; never raises."""
    p = provider()
    if not p:
        log.warning("email (not sent, no mail provider configured) to=%s subject=%s link=%s", to, subject, link)
        return False
    html_body = _layout(title, body, cta, link)
    text_body = f"{title}\n\n{html.unescape(body)}\n\n{cta}: {link}"
    default_from = os.environ.get("GMAIL_ADDRESS") or "onboarding@resend.dev"
    sender = os.environ.get("MAIL_FROM") or f"BrandProof <{default_from}>"
    secrets = [v for k, v in os.environ.items() if k in ("RESEND_API_KEY", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_APP_PASSWORD") and v]
    try:
        if p == "resend":
            r = httpx.post("https://api.resend.com/emails", timeout=15, headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                           json={"from": sender, "to": [to], "subject": subject, "html": html_body, "text": text_body})
            r.raise_for_status()
        elif p == "gmail-api":
            _gmail_api(_mime(to, subject, html_body, text_body, sender))
        else:
            _gmail_smtp(_mime(to, subject, html_body, text_body, sender))
        return True
    except Exception as e:
        msg = str(e)
        for sec in secrets:
            msg = msg.replace(sec, "***")
        log.warning("email via %s to %s failed: %s", p, to, msg)
        return False
