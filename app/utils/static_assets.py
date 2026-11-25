"""
Cache-busted URLs for files under app/static.

`{{ asset_url('js/model_sidebar.js') }}` renders
`/static/js/model_sidebar.js?v=<file mtime>`, so browsers fetch the new file
as soon as it changes instead of running a stale cached copy after an
update (plain `url_for('static', ...)` URLs never change).
"""
from __future__ import annotations

import os

from flask import current_app, url_for


def asset_url(filename: str) -> str:
    try:
        version = int(os.path.getmtime(os.path.join(current_app.static_folder, filename)))
    except (OSError, TypeError):
        version = 0
    return url_for("static", filename=filename, v=version)


def asset_url_context() -> dict:
    """Context processor: makes asset_url() available in templates.
    Registered app-wide by the pages blueprint (app/routes/page_routes.py),
    so any app that serves the HTML pages has it."""
    return {"asset_url": asset_url}
