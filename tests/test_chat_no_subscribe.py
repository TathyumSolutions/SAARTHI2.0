"""
Subscriptions are created only from the Alerts & Subscriptions screen under
Management, never from a chat answer. Guard the chat page against a
Subscribe button or option creeping back in.
"""
import os
import re

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_TEMPLATES = ["index.html", "base.html"]


@pytest.mark.parametrize("name", CHAT_TEMPLATES)
def test_chat_page_has_no_subscribe(name):
    path = os.path.join(ROOT_DIR, "app", "templates", name)
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    assert not re.search(r"subscri", html, re.IGNORECASE), (
        f"{name} offers subscribe in the chat; subscriptions belong on the "
        "Management > Alerts & Subscriptions screen only"
    )
