"""
Outbound Email Service
Sends transactional emails (currently just signup verification) over SMTP.

Configured entirely through environment variables so no code change is
needed to point this at a real mail provider:
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
  SMTP_FROM_EMAIL (default SMTP_USER)

Two distinct "secure SMTP" modes exist and providers aren't
interchangeable between them - picking the wrong one just times out:
  - Implicit SSL/TLS (typically port 465): the connection is encrypted
    from the first byte. Used automatically when SMTP_PORT=465, or force
    it explicitly with SMTP_USE_SSL=true for a provider using a
    non-standard port.
  - STARTTLS (typically port 587): connects in plaintext, then upgrades.
    This is the default for every other port. Disable with
    SMTP_USE_TLS=false only for providers that genuinely don't support
    encryption at all (rare, not recommended).

If SMTP_HOST isn't set (e.g. local development), the email is logged to
the console instead of being sent, so registration still works end to end
without requiring real mail infrastructure.
"""
import os
import smtplib
import ssl
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

        # Implicit SSL (SMTPS) defaults on for port 465 - the standard for
        # that port - or can be forced for a non-standard port via
        # SMTP_USE_SSL. Everything else falls through to STARTTLS.
        ssl_env = os.environ.get('SMTP_USE_SSL')
        use_ssl = (ssl_env.strip().lower() in ('true', '1', 'yes')) if ssl_env is not None else (port == 465)

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls(context=ssl.create_default_context())

        try:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        finally:
            server.quit()
        return True
    except Exception as e:
        print(f"[Email Service] Failed to send verification email to {to_email}: {e}")
        return False
