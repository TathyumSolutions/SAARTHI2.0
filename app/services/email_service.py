"""
Outbound Email Service
Sends transactional emails (currently just signup verification) over SMTP.

Configured entirely through environment variables so no code change is
needed to point this at a real mail provider:
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
  SMTP_FROM_EMAIL (default SMTP_USER), SMTP_USE_TLS (default true)

If SMTP_HOST isn't set (e.g. local development), the email is logged to
the console instead of being sent, so registration still works end to end
without requiring real mail infrastructure.
"""
import os
import smtplib
from email.message import EmailMessage


def _smtp_configured():
    return bool(os.environ.get('SMTP_HOST'))


def send_verification_email(to_email, name, verification_link):
    """
    Sends the "verify your email" message for a freshly registered account.
    Falls back to logging the link to the console when SMTP isn't configured.
    """
    subject = "Verify your Saarthi account"
    body = (
        f"Hi {name},\n\n"
        f"Thanks for signing up for Saarthi. Please verify your email address "
        f"by opening the link below:\n\n"
        f"{verification_link}\n\n"
        f"This link expires in 24 hours. If you didn't create this account, "
        f"you can safely ignore this email.\n\n"
        f"- The Saarthi team"
    )

    if not _smtp_configured():
        print(f"[Email Service] SMTP not configured - verification link for {to_email}: {verification_link}")
        return True

    try:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = os.environ.get('SMTP_FROM_EMAIL') or os.environ.get('SMTP_USER')
        msg['To'] = to_email
        msg.set_content(body)

        host = os.environ.get('SMTP_HOST')
        port = int(os.environ.get('SMTP_PORT', '587'))
        user = os.environ.get('SMTP_USER')
        password = os.environ.get('SMTP_PASSWORD')
        use_tls = os.environ.get('SMTP_USE_TLS', 'true').strip().lower() not in ('false', '0', 'no')

        with smtplib.SMTP(host, port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[Email Service] Failed to send verification email to {to_email}: {e}")
        return False
