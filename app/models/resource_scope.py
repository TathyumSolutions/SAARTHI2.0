"""
Resource Scope - shared columns + visibility rule for every data-resource
table (files, database_connections, api_connectors).

A resource is either:
- 'shared' (the default, and every resource that existed before this
  column did): visible to its creator plus anyone an admin grants it to
  via Resource Mapping - the same "own + granted" rule as always.
- 'session_local': uploaded from the chat box's attach (+) button. Visible
  ONLY to its creator, and ONLY inside the one chat session it was
  uploaded in (chat_session_id = chat_sessions.session_id). It can never
  be granted to anyone through Resource Mapping, never shows up in the
  Knowledge Base / Data Sources lists, and is deleted - along with all its
  metadata, vectors and Parquet data - when that chat session is deleted
  (see app/services/session_resource_service.py).

chat_sessions lives in the 'workspace' bind while these tables live in
'resources' - separate Postgres databases - so chat_session_id can't be a
real foreign key; the link is enforced in application code instead.
"""
from app import db

SCOPE_SHARED = 'shared'
SCOPE_SESSION_LOCAL = 'session_local'
SCOPES = (SCOPE_SHARED, SCOPE_SESSION_LOCAL)


class ResourceScopeMixin:
    scope = db.Column(db.String(20), nullable=False, default=SCOPE_SHARED, index=True)
    chat_session_id = db.Column(db.String(255), nullable=True, index=True)

    @property
    def is_session_local(self):
        return self.scope == SCOPE_SESSION_LOCAL


def is_session_local(resource):
    return getattr(resource, 'scope', SCOPE_SHARED) == SCOPE_SESSION_LOCAL


def visibility_filter(model, user_id, granted_ids, chat_session_id=None):
    """
    SQLAlchemy filter expression for rows of `model` this user can use:
    shared rows they created or were granted, plus - only when a
    chat_session_id is given - their own session-local rows from that
    exact session. Without a chat_session_id no session-local row is ever
    visible, so every caller outside a chat question (Knowledge Base
    lists, status checks, admin screens) keeps seeing shared resources only.
    """
    shared = (model.scope == SCOPE_SHARED) & (
        (model.created_by_user_id == user_id) | model.id.in_(list(granted_ids or []) or [-1])
    )
    if not chat_session_id:
        return shared
    local = (
        (model.scope == SCOPE_SESSION_LOCAL)
        & (model.created_by_user_id == user_id)
        & (model.chat_session_id == str(chat_session_id))
    )
    return shared | local
