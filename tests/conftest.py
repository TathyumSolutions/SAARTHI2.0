"""
Shared test setup.

app.services.llm_service builds a real HuggingFaceEmbeddings client at
import time, which reaches out to the HF hub - not available offline (and
langchain_huggingface itself may not be installed). Any test importing
router_service needs it stubbed first; doing it here, once, means a test
no longer depends on some other test file having been collected before it.
"""
import importlib.util
import sys
from unittest.mock import MagicMock

if importlib.util.find_spec("langchain_huggingface") is None:
    _fake_hf = MagicMock()
    _fake_hf.HuggingFaceEmbeddings = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("langchain_huggingface", _fake_hf)
