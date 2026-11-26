"""
Chat bar <-> Settings > Model Selection sync.

The chat bar saves its model as the pipeline's main model
(PUT /api/user/model-pipeline/main-model) and reads it back on load, so the
two always show the same model. Runs against in-memory SQLite with only the
model-pipeline blueprint.
"""
import os
import sys

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import db  # noqa: E402
from app.models.model_config import ModelConfiguration  # noqa: E402
from app.models.user_model_pipeline import UserModelPipeline  # noqa: E402

USER_ID = 5


@pytest.fixture
def client():
    from app.routes import user_model_pipeline_routes

    flask_app = Flask(__name__)
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_BINDS={"core": "sqlite://", "resources": "sqlite://", "workspace": "sqlite://"},
        JWT_SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
    )
    db.init_app(flask_app)
    JWTManager(flask_app)
    flask_app.register_blueprint(user_model_pipeline_routes.bp)
    with flask_app.app_context():
        db.create_all()
        db.session.add(ModelConfiguration(name="GPT-4o", model="api://gpt-4o", provider="OpenAI",
                                          settings={}, user_id=USER_ID))
        db.session.commit()
        token = create_access_token(identity=str(USER_ID))
        test_client = flask_app.test_client()
        test_client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        yield test_client
        db.session.remove()
        db.drop_all()


def _pipeline():
    return UserModelPipeline.query.filter_by(user_id=USER_ID).first()


def test_chat_bar_change_creates_the_setting(client):
    res = client.put("/api/user/model-pipeline/main-model", json={"main_model": "api://gpt-4o"})
    assert res.status_code == 200, res.json
    assert _pipeline().main_model == "api://gpt-4o"
    assert client.get("/api/user/model-pipeline").json["config"]["main_model"] == "api://gpt-4o"


def test_overrides_that_repeated_the_old_main_model_follow_the_new_one(client):
    db.session.add(UserModelPipeline(
        user_id=USER_ID, main_model="llama2:7b",
        step_models={"Query Sense": "llama2:7b", "SQL Generator": "api://gpt-4o"},
    ))
    db.session.commit()

    client.put("/api/user/model-pipeline/main-model", json={"main_model": "ollama://llama2:7b"})
    client.put("/api/user/model-pipeline/main-model", json={"main_model": "api://gpt-4o"})

    pipeline = _pipeline()
    assert pipeline.main_model == "api://gpt-4o"
    # "Query Sense: llama2:7b" only mirrored the old main model -> dropped;
    # the deliberate "SQL Generator" choice is kept.
    assert pipeline.step_models == {"SQL Generator": "api://gpt-4o"}


def test_unknown_model_is_rejected(client):
    res = client.put("/api/user/model-pipeline/main-model", json={"main_model": "api://made-up"})
    assert res.status_code == 400


def test_settings_page_accepts_configured_model_ids(client):
    res = client.post("/api/user/model-pipeline", json={
        "main_model": "api://gpt-4o", "model_type_preference": "api",
        "step_models": {"SQL Generator": "ollama://llama2:7b"},
    })
    assert res.status_code == 200, res.json
    assert _pipeline().step_models == {"SQL Generator": "ollama://llama2:7b"}


def test_requires_login(client):
    client.environ_base.pop("HTTP_AUTHORIZATION")
    res = client.put("/api/user/model-pipeline/main-model", json={"main_model": "api://gpt-4o"})
    assert res.status_code == 401
