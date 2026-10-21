"""
Subscriptions are created only from the Alerts & Subscriptions screen under
Management, never from a chat answer. Guard the chat page against a
Subscribe button or option creeping back in.

base.html is the layout every page shares, and its sidebar carries the two
"Alerts & Subscriptions" menu items (Reports and Management) - those are
the only mentions it may have.
"""
import os
import re

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT_DIR, "app", "templates")
MENU_LABEL = "<span>Alerts &amp; Subscriptions</span>"


def _read(name):
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
        return fh.read()


def test_chat_page_has_no_subscribe():
    assert not re.search(r"subscri", _read("index.html"), re.IGNORECASE), (
        "index.html offers subscribe in the chat; subscriptions belong on the "
        "Management > Alerts & Subscriptions screen only"
    )


def test_layout_mentions_subscriptions_only_in_the_two_menu_items():
    html = _read("base.html")
    assert html.count(MENU_LABEL) == 2
    rest = html.replace(MENU_LABEL, "")
    assert not re.search(r"subscri", rest, re.IGNORECASE), (
        "base.html offers subscribe outside the Alerts & Subscriptions menu items; "
        "subscriptions belong on the Management > Alerts & Subscriptions screen only"
    )


def test_menu_items_open_the_alerts_pages():
    html = _read("base.html")
    assert "window.location.href='/alerts'" in html       # Reports: the list
    assert "window.location.href='/alerts/new'" in html   # Management: create
    management = html[html.index('<div class="section-title">Management</div>'):]
    assert management.index("Resource Mapping") < management.index(MENU_LABEL)
