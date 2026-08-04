"""
Audit Service - one shared helper for writing to the audit log, so every
mutation that matters (signup, login, approval, resource create/delete,
resource-mapping grants) goes through the same code path instead of each
route hand-rolling its own logging (or, as before, none at all).
"""
from app import db
from app.models.audit_log import AuditLog


def log_event(action, company_code=None, user_id=None, resource_type=None, resource_id=None, details=None, ip_address=None):
    """
    Writes one audit log entry. Never raises - a logging failure should
    never take down the request that triggered it, so errors are swallowed
    and printed instead.
    """
    try:
        entry = AuditLog(
            company_code=company_code,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Audit Service] Failed to log event '{action}': {e}")
