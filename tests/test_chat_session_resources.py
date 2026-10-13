"""
Tests for files attached to one chat via the chat box's attach (+) button
(app/services/session_resource_service.py, app/models/resource_scope.py):

  1. Attaching stores documents as FileResource and Excel/CSV as
     DatabaseConnection rows tagged scope='session_local' + the chat id,
     creating the chat session row if the chat hasn't been saved yet.
  2. Only the uploader, asking in that same chat, can see them - not in
     another chat of theirs, not another user, not the Knowledge Base /
     Data Sources lists, and never through Resource Mapping.
  3. Deleting the chat deletes its attachments and their stored data.
"""
import io
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token

from app import create_app, db, limiter
from app.models.chat import ChatSession
from app.models.database_connection import DatabaseConnection
from app.models.file_resource import FileResource
from app.models.resource_scope import SCOPE_SESSION_LOCAL, SCOPE_SHARED
from app.models.user import User
from app.services import spreadsheet_service


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = create_app('testing')
    limiter.enabled = False
    monkeypatch.setattr(spreadsheet_service, "SPREADSHEET_FOLDER", str(tmp_path / "sheets"))
    monkeypatch.setattr(spreadsheet_service, "MANIFEST_FILE", str(tmp_path / "sheets" / "manifest.json"))
    from app.routes import upload_routes
    monkeypatch.setattr(upload_routes, "UPLOAD_FOLDER", str(tmp_path / "uploads"))

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    limiter.enabled = True


@pytest.fixture
def client(app):
    return app.test_client()


def _user(email):
    user = User(name=email.split('@')[0], email=email, password_hash='x', role='admin', status='active')
    db.session.add(user)
    db.session.commit()
    return user


def _headers(user):
    return {'Authorization': f'Bearer {create_access_token(identity=str(user.id))}'}


def _attach(client, user, session_id, *files):
    data = {'files': [(io.BytesIO(content), name) for name, content in files]}
    return client.post(f'/api/chat/sessions/{session_id}/resources', data=data,
                       headers=_headers(user), content_type='multipart/form-data')


CSV = b"region,sales\nNorth,10\nSouth,20\n"
TXT = b"The refund policy allows returns within 30 days."


def test_attach_tags_resources_to_the_chat_and_creates_the_session(client):
    alice = _user('alice@example.com')

    res = _attach(client, alice, 'session_A', ('notes.txt', TXT), ('sales.csv', CSV))

    assert res.status_code == 201, res.json
    kinds = sorted(r['kind'] for r in res.json['resources'])
    assert kinds == ['file', 'spreadsheet']
    assert all(r['status'] == 'uploaded' and r['process_url'] for r in res.json['resources'])

    f = FileResource.query.one()
    c = DatabaseConnection.query.one()
    for row in (f, c):
        assert row.scope == SCOPE_SESSION_LOCAL
        assert row.chat_session_id == 'session_A'
        assert row.created_by_user_id == alice.id
    assert c.type == 'Excel'
    assert spreadsheet_service.get_tables_for_connection(c.id)

    session = ChatSession.query.filter_by(session_id='session_A').one()
    assert session.user_id == alice.id

    listed = client.get('/api/chat/sessions/session_A/resources', headers=_headers(alice)).json['resources']
    assert sorted(r['name'] for r in listed) == ['notes.txt', 'sales']


def test_only_the_uploader_in_the_same_chat_can_see_attachments(client):
    from app.services.automated_metamind import visible_document_codes, introspect_spreadsheets

    alice = _user('alice@example.com')
    bob = _user('bob@example.com')
    _attach(client, alice, 'session_A', ('notes.txt', TXT), ('sales.csv', CSV))
    code = FileResource.query.one().document_code
    table = spreadsheet_service.list_all_tables()[0]['table']

    assert visible_document_codes(alice.id, 'session_A') == [code]
    assert visible_document_codes(alice.id) == []
    assert visible_document_codes(alice.id, 'session_B') == []
    assert visible_document_codes(bob.id, 'session_A') == []

    assert table in (introspect_spreadsheets(alice.id, 'session_A') or {})
    assert introspect_spreadsheets(alice.id) is None
    assert introspect_spreadsheets(bob.id, 'session_A') is None

    # Not in the Knowledge Base / Data Sources lists, even for the uploader.
    assert client.get('/api/upload/files', headers=_headers(alice)).json['files'] == []
    assert client.get('/api/databases/', headers=_headers(alice)).json['databases'] == []

    # Another user can't reach the chat or its files directly.
    assert client.get('/api/chat/sessions/session_A/resources', headers=_headers(bob)).status_code == 404
    assert _attach(client, bob, 'session_A', ('x.txt', TXT)).status_code == 404
    assert client.get(f'/api/files/view/{code}', headers=_headers(bob)).status_code == 403


def test_attachments_can_never_be_granted_through_resource_mapping(client):
    from app.routes.resource_mapping_routes import _resource_lookup

    alice = _user('alice@example.com')
    _attach(client, alice, 'session_A', ('notes.txt', TXT), ('sales.csv', CSV))
    f = FileResource.query.one()
    c = DatabaseConnection.query.one()

    assert _resource_lookup('file', f.id, f.company_code) is None
    assert _resource_lookup('database', c.id, c.company_code) is None

    f.scope = SCOPE_SHARED
    db.session.commit()
    assert _resource_lookup('file', f.id, f.company_code) is f


def test_unsupported_file_type_is_rejected(client):
    alice = _user('alice@example.com')
    res = _attach(client, alice, 'session_A', ('movie.mp4', b'\x00\x01'))
    assert res.status_code == 400
    assert FileResource.query.count() == 0


def test_spreadsheet_table_names_never_collide(client):
    alice = _user('alice@example.com')
    _attach(client, alice, 'session_A', ('sales.csv', CSV))
    _attach(client, alice, 'session_B', ('sales.csv', CSV))
    names = [t['table'] for t in spreadsheet_service.list_all_tables()]
    assert len(names) == 2 and len(set(names)) == 2


def test_deleting_the_chat_deletes_its_attachments_and_their_data(client):
    alice = _user('alice@example.com')
    _attach(client, alice, 'session_A', ('notes.txt', TXT), ('sales.csv', CSV))
    _attach(client, alice, 'session_B', ('other.txt', TXT))
    file_a = FileResource.query.filter_by(chat_session_id='session_A').one()
    file_path, code = file_a.file_path, file_a.document_code

    from app.routes import datasource_routes
    with patch.object(datasource_routes.llm_service, 'delete_document_vectors') as purge:
        res = client.delete('/api/chat/sessions/session_A', headers=_headers(alice))

    assert res.status_code == 200
    purge.assert_called_once_with(code)
    assert ChatSession.query.filter_by(session_id='session_A').first() is None
    assert FileResource.query.filter_by(chat_session_id='session_A').count() == 0
    assert DatabaseConnection.query.count() == 0
    assert spreadsheet_service.list_all_tables() == []
    import os
    assert not os.path.exists(file_path)
    # The other chat's attachment is untouched.
    assert FileResource.query.filter_by(chat_session_id='session_B').count() == 1


def test_removing_one_attachment(client):
    alice = _user('alice@example.com')
    bob = _user('bob@example.com')
    _attach(client, alice, 'session_A', ('sales.csv', CSV))
    c = DatabaseConnection.query.one()

    url = f'/api/chat/sessions/session_A/resources/spreadsheet/{c.id}'
    assert client.delete(url, headers=_headers(bob)).status_code == 404
    assert client.delete(url, headers=_headers(alice)).status_code == 200
    assert DatabaseConnection.query.count() == 0


def test_attachments_are_processed_by_the_same_process_endpoints(client):
    """Same pipeline as a Knowledge Base upload - the Process endpoints the
    attach response points at - with the chunks tagged with their chat and
    the router check run inside that chat (where the attachment is visible)."""
    from app.routes import datasource_routes

    alice = _user('alice@example.com')
    resources = _attach(client, alice, 'session_A', ('notes.txt', TXT)).json['resources']

    with patch.object(datasource_routes.llm_service, 'process_to_embeddings',
                      return_value={'status': 'success', 'chunk_count': 1, 'content_summary': 'Refund policy.'}) as embed, \
         patch('app.services.automated_metamind.generate_router_config') as router_check:
        res = client.post(resources[0]['process_url'], headers=_headers(alice))

    assert res.status_code == 200, res.json
    assert embed.call_args.kwargs['extra_metadata'] == {'scope': SCOPE_SESSION_LOCAL, 'chat_session_id': 'session_A'}
    router_check.assert_called_once_with(user_id=alice.id, chat_session_id='session_A')
    assert FileResource.query.one().status == 'processed'
