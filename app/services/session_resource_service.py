"""
Session Resource Service - files and spreadsheets attached to one chat.

The chat box's attach (+) button uploads local files into the CURRENT chat
session only. They go through exactly the same pipeline as a Knowledge
Base upload - documents become a FileResource (embedded into Qdrant on
Process), Excel/CSV becomes one Parquet-backed DatabaseConnection per sheet
(summarized on Process) - and differ only in being tagged
scope='session_local' + chat_session_id (see app/models/resource_scope.py):

- visible only to the uploader, and only while asking in that chat;
- never listed in the Knowledge Base / Data Sources / Resource Mapping
  screens, and never grantable to another user;
- deleted, with all their metadata, vectors and Parquet data, when the
  chat session itself is deleted (delete_session_resources).
"""
import os

from app import db
from app.models.chat import ChatSession
from app.models.database_connection import DatabaseConnection
from app.models.file_resource import FileResource
from app.models.resource_scope import SCOPE_SESSION_LOCAL

DOCUMENT_EXTENSIONS = {'pdf', 'docx', 'txt', 'md'}
SPREADSHEET_EXTENSIONS = {'xlsx', 'xls', 'csv'}
ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | SPREADSHEET_EXTENSIONS

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_RESOURCES_PER_SESSION = 20


class SessionAccessError(Exception):
    """The chat session exists but belongs to someone else."""


def _extension(filename):
    return filename.rsplit('.', 1)[-1].lower() if filename and '.' in filename else ''


def get_owned_session(session_id, user, create=False):
    """
    The ChatSession `session_id` if it belongs to `user`. Session ids are
    minted in the browser and only saved on the server once the chat is
    first checkpointed (see base.html's saveActiveChatToHistory) - so
    attaching a file as the very first thing in a brand-new chat has no
    row yet; create=True makes one then, owned by this user, so the
    attachment has a session to belong to. Returns None if missing (and not
    created); raises SessionAccessError if it's another user's.
    """
    session = ChatSession.query.filter_by(session_id=session_id).first()
    if session:
        if session.user_id != user.id:
            raise SessionAccessError(session_id)
        return session
    if not create:
        return None
    session = ChatSession(
        session_id=session_id,
        title='New chat',
        chat_history='',
        company_code=user.company_code,
        user_id=user.id,
    )
    db.session.add(session)
    db.session.commit()
    return session


def _session_files(session_id, user_id):
    return FileResource.query.filter_by(
        scope=SCOPE_SESSION_LOCAL, chat_session_id=session_id, created_by_user_id=user_id
    ).order_by(FileResource.created_at).all()


def _session_connections(session_id, user_id):
    return DatabaseConnection.query.filter_by(
        scope=SCOPE_SESSION_LOCAL, chat_session_id=session_id, created_by_user_id=user_id
    ).order_by(DatabaseConnection.created_at).all()


def _serialize_file(resource):
    return {
        'kind': 'file',
        'id': resource.document_code,
        'name': resource.file_name,
        'status': resource.status or 'uploaded',
        'error_message': resource.error_message,
        'process_url': f'/api/datasources/unstructured/{resource.document_code}/process',
    }


def _serialize_connection(connection):
    # Excel connections use 'connected' for "uploaded, not processed yet".
    status = connection.status if connection.status in ('processed', 'error') else 'uploaded'
    return {
        'kind': 'spreadsheet',
        'id': connection.id,
        'name': connection.name,
        'status': status,
        'error_message': connection.error_message,
        'process_url': f'/api/databases/{connection.id}/process',
    }


def list_session_resources(session_id, user):
    return (
        [_serialize_file(f) for f in _session_files(session_id, user.id)]
        + [_serialize_connection(c) for c in _session_connections(session_id, user.id)]
    )


def _file_size(file):
    stream = file.stream
    position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(position)
    return size


def add_session_resources(session_id, user, files):
    """
    Saves each uploaded file into chat `session_id` (creating the session
    row if this is the chat's first server-side action) and returns the
    serialized new attachments, each with the process_url the client calls
    next - the same Process endpoint the Knowledge Base uses. Raises
    ValueError (message safe to show) for a bad file; files before it in
    the batch stay attached.
    """
    from app.routes.upload_routes import save_unstructured_upload
    from app.routes.database_routes import create_spreadsheet_connections

    files = [f for f in files if f and f.filename]
    if not files:
        raise ValueError('No file selected')

    get_owned_session(session_id, user, create=True)

    existing = len(_session_files(session_id, user.id)) + len(_session_connections(session_id, user.id))
    if existing + len(files) > MAX_RESOURCES_PER_SESSION:
        raise ValueError(f'A chat can have at most {MAX_RESOURCES_PER_SESSION} attachments.')

    for file in files:
        if _extension(file.filename) not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"'{file.filename}' can't be attached - supported types: "
                + ', '.join(sorted(ALLOWED_EXTENSIONS))
            )
        if _file_size(file) > MAX_FILE_BYTES:
            raise ValueError(f"'{file.filename}' is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    added = []
    for file in files:
        local = {'scope': SCOPE_SESSION_LOCAL, 'chat_session_id': session_id}
        if _extension(file.filename) in SPREADSHEET_EXTENSIONS:
            name = os.path.splitext(file.filename)[0] or 'attachment'
            connections, *_ = create_spreadsheet_connections(
                user, file.read(), file.filename, name, **local
            )
            added.extend(_serialize_connection(c) for c in connections)
        else:
            resource = save_unstructured_upload(user, file, 'documents', **local)
            added.append(_serialize_file(resource))
    return added


def delete_session_resource(session_id, user, kind, resource_id):
    """Removes one attachment from a chat. Returns False if it isn't an
    attachment of this user's chat `session_id`."""
    from app.routes.datasource_routes import delete_file_resource
    from app.routes.database_routes import delete_connection_resource

    if kind == 'file':
        resource = FileResource.query.filter_by(
            document_code=str(resource_id), scope=SCOPE_SESSION_LOCAL,
            chat_session_id=session_id, created_by_user_id=user.id,
        ).first()
        if not resource:
            return False
        delete_file_resource(resource)
        return True
    if kind == 'spreadsheet':
        try:
            connection_id = int(resource_id)
        except (TypeError, ValueError):
            return False
        connection = DatabaseConnection.query.filter_by(
            id=connection_id, scope=SCOPE_SESSION_LOCAL,
            chat_session_id=session_id, created_by_user_id=user.id,
        ).first()
        if not connection:
            return False
        delete_connection_resource(connection)
        return True
    return False


def delete_session_resources(session_id, user_id):
    """
    Deletes every attachment of chat `session_id` owned by `user_id` -
    files (row, metamind_summary, Qdrant chunks, file on disk) and
    spreadsheets (row, schema_metadata, Parquet tables, manifest entry).
    Called before the chat session row itself is deleted. Best-effort per
    attachment: one failing never blocks the rest, or the chat's deletion.
    Returns the number of attachments deleted.
    """
    from app.routes.datasource_routes import delete_file_resource
    from app.routes.database_routes import delete_connection_resource

    deleted = 0
    for resource in _session_files(session_id, user_id):
        try:
            delete_file_resource(resource, strict=False)
            deleted += 1
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Could not delete chat attachment {resource.document_code}: {e}")
    for connection in _session_connections(session_id, user_id):
        try:
            delete_connection_resource(connection)
            deleted += 1
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Could not delete chat spreadsheet {connection.id}: {e}")
    return deleted
