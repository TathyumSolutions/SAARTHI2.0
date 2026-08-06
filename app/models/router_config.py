"""
Router Config Model - one row per user, holding their personal
metamind router config (which datasources/tables/API tools/spreadsheets
the smart router considers when answering their questions) and its
trimmed summary.

Replaces the old app/services/metamind_router_config.json +
metamind_router_config_summary.json + .router_config_hash files, which
were global - shared across every user regardless of which resources
they actually have access to. Each user's config now only reflects
resources they created or were explicitly granted via Resource Mapping.
"""
from app import db
from datetime import datetime


class RouterConfig(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'router_configs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)

    config = db.Column(db.JSON, nullable=True)
    summary = db.Column(db.JSON, nullable=True)
    # Content fingerprint of the last-generated config, used to skip
    # regeneration when nothing actually changed - replaces the old
    # single global .router_config_hash file.
    fingerprint = db.Column(db.String(64), nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
