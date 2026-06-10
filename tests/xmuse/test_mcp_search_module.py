from __future__ import annotations

from xmuse.mcp_server import _query_terms as legacy_query_terms
from xmuse.mcp_server import _text_for_search as legacy_text_for_search
from xmuse_core.platform import mcp_search


def test_mcp_search_module_owns_nested_text_flattening() -> None:
    assert mcp_search.text_for_search(
        {"title": "Alpha", "items": ["Beta", {"note": "Gamma"}]}
    ) == "Alpha Beta Gamma"


def test_mcp_search_module_owns_query_terms() -> None:
    assert mcp_search.query_terms("Fix P0-A + review_god x") == {
        "fix",
        "p0-a",
        "review_god",
    }


def test_mcp_server_preserves_search_helper_compat_exports() -> None:
    assert legacy_text_for_search is mcp_search.text_for_search
    assert legacy_query_terms is mcp_search.query_terms
