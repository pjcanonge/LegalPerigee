"""
Email alert sender for LegalPerigee.  (v1.2 — security-hardened)

Checks newly synced cases against saved alert rules and sends
email digests via SMTP (Gmail, Outlook, or custom).

Credentials are stored ONLY in macOS Keychain (loaded by window.py at startup).
Do NOT place email credentials in any .env file.

Security (v1.2):
  - H-5: All database-sourced fields are HTML-escaped before insertion into
          the email template.  document_url is validated to start with https://.
  - L-2: SMTP exceptions logged by exception type only (no credential leakage).
"""

import html as _html_mod
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from database.db import (
    get_alert_rules, mark_alert_sent, search_cases, touch_alert_rule,
    init_alerts_table,
)

# ── SMTP config from environment ──────────────────────────────────────────────

def _smtp_config() -> dict:
    return {
        "host": os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("ALERT_SMTP_PORT", "587")),
        "from": os.getenv("ALERT_EMAIL_FROM", ""),
        "password": os.getenv("ALERT_EMAIL_PASSWORD", ""),
    }


def smtp_configured() -> bool:
    cfg = _smtp_config()
    return bool(cfg["from"] and cfg["password"])


# ── HTML email template ───────────────────────────────────────────────────────

def _safe_url(raw: str) -> str:
    """
    H-5: Return the URL only if it begins with https:// — otherwise '#'.
    Prevents javascript: URIs or relative paths from becoming href values.
    """
    stripped = (raw or "").strip()
    return stripped if stripped.startswith("https://") else "#"


def _build_email_html(rule_name: str, matches: list[dict]) -> str:
    # H-5: escape every field that comes from external API / database data
    safe_rule = _html_mod.escape(rule_name)
    rows = ""
    for c in matches:
        url     = _safe_url(c.get("document_url", ""))          # validated URL
        name    = _html_mod.escape(c.get("case_name", "Untitled"))
        court   = _html_mod.escape(c.get("court", "Unknown"))
        date    = _html_mod.escape(c.get("filing_date", "Unknown"))
        summary = _html_mod.escape((c.get("summary") or "")[:200])
        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:12px 8px;">
            <a href="{url}" style="color:#1a2744;font-weight:600;text-decoration:none;">{name}</a><br>
            <span style="color:#888;font-size:.85rem;">{court} · {date}</span><br>
            <span style="color:#555;font-size:.85rem;">{summary}</span>
          </td>
        </tr>"""

    return f"""
<!DOCTYPE html>
<html>
<body style="font-family:Helvetica,Arial,sans-serif;background:#f4f6fb;margin:0;padding:20px;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:10px;
              box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden;">
    <div style="background:linear-gradient(135deg,#1a2744,#0d1b2a);
                padding:28px 32px;border-left:5px solid #c9a84c;">
      <h1 style="color:#e8d9b0;margin:0;font-size:1.5rem;">⚖️ LegalPerigee Alert</h1>
      <p style="color:#8fa3bf;margin:4px 0 0;font-size:.9rem;">
        Rule: <strong style="color:#c9a84c;">{safe_rule}</strong> ·
        {len(matches)} new case{"s" if len(matches)!=1 else ""}
      </p>
    </div>
    <div style="padding:24px 32px;">
      <p style="color:#333;margin-top:0;">
        New cases matching your alert were found:
      </p>
      <table style="width:100%;border-collapse:collapse;">
        {rows}
      </table>
      <p style="color:#aaa;font-size:.8rem;margin-top:24px;border-top:1px solid #eee;padding-top:12px;">
        Sent by LegalPerigee · {datetime.now().strftime("%Y-%m-%d %H:%M")} ·
        <a href="http://localhost:8501" style="color:#1a2744;">Open App</a>
      </p>
    </div>
  </div>
</body>
</html>"""


def _build_email_text(rule_name: str, matches: list[dict]) -> str:
    lines = [
        f"LegalPerigee Alert — Rule: {rule_name}",
        f"{len(matches)} new case(s) found\n",
    ]
    for c in matches:
        lines.append(f"• {c.get('case_name','Untitled')}")
        lines.append(f"  {c.get('court','')} · {c.get('filing_date','')}")
        if c.get("document_url"):
            lines.append(f"  {c['document_url']}")
        lines.append("")
    return "\n".join(lines)


# ── Send ──────────────────────────────────────────────────────────────────────

def send_alert_email(to: str, rule_name: str, matches: list[dict]) -> bool:
    """Send an alert email. Returns True on success."""
    cfg = _smtp_config()
    if not cfg["from"] or not cfg["password"]:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚖️ LegalPerigee Alert: {len(matches)} new case(s) — {rule_name}"
    msg["From"] = cfg["from"]
    msg["To"] = to

    msg.attach(MIMEText(_build_email_text(rule_name, matches), "plain"))
    msg.attach(MIMEText(_build_email_html(rule_name, matches), "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(cfg["from"], cfg["password"])
            server.sendmail(cfg["from"], to, msg.as_string())
        return True
    except Exception as e:
        # L-2: Log only the exception type — never the message (may contain credentials)
        import sys as _sys
        print(f"[alerts] Email send failed ({type(e).__name__})", file=_sys.stderr)
        return False


# ── Check and dispatch ────────────────────────────────────────────────────────

def check_and_send_alerts(
    days_lookback: int = 1,
    progress_cb=None,
) -> dict:
    """
    Check all active alert rules against recently added cases.
    Sends emails for new matches. Returns summary dict.
    """
    init_alerts_table()
    rules = get_alert_rules()
    if not rules:
        return {"alerts_checked": 0, "emails_sent": 0}

    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days_lookback)).strftime("%Y-%m-%d")

    emails_sent = 0
    alerts_checked = len(rules)

    for rule in rules:
        keywords = rule.get("keywords", "") or ""
        email = rule.get("email", "")
        if not email:
            continue

        # Find matching cases added since cutoff
        candidates = search_cases(
            q=keywords,
            date_from=cutoff,
            limit=50,
        )

        # Filter by court/state if rule specifies
        courts_filter = [c.strip() for c in (rule.get("courts") or "").split(",") if c.strip()]
        states_filter = [s.strip() for s in (rule.get("states") or "").split(",") if s.strip()]

        if courts_filter:
            candidates = [c for c in candidates
                          if any(cf.lower() in (c.get("court") or "").lower()
                                 for cf in courts_filter)]
        if states_filter:
            candidates = [c for c in candidates
                          if any(sf.lower() in (c.get("jurisdiction") or "").lower()
                                 for sf in states_filter)]

        # De-duplicate against already-sent alerts
        new_matches = [c for c in candidates if mark_alert_sent(rule["id"], c["id"])]

        if new_matches:
            if progress_cb:
                progress_cb(f"Alert '{rule['name']}': {len(new_matches)} match(es) → {email}")
            if send_alert_email(email, rule["name"], new_matches):
                emails_sent += 1
            else:
                if progress_cb:
                    progress_cb(f"  ⚠️ Email send failed (check SMTP settings)")

        touch_alert_rule(rule["id"])

    return {"alerts_checked": alerts_checked, "emails_sent": emails_sent}
