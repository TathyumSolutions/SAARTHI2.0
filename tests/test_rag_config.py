import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.rag_config import load_rag_config, get_rag_setting


def test_rag_config_loader_reads_expected_defaults():
    config = load_rag_config()

    assert config["embedding"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert config["vector_store"]["collection_name"] == "saarthi_unstructured"
    assert config["chunking"]["chunk_size"] == 800
    assert config["chunking"]["chunk_overlap"] == 80
    assert config["retrieval"]["top_k"] == 3


def test_get_rag_setting_supports_nested_keys():
    assert get_rag_setting("retrieval.top_k") == 3
    assert get_rag_setting("chunking.table.enabled") is False
