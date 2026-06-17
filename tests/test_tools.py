"""
tests/test_tools.py

Tool-level tests for FitFindr. Run with:  pytest tests/

These cover the happy path AND each tool's documented failure mode. The two
LLM-backed tools (suggest_outfit, create_fit_card) degrade to a non-empty
fallback string when no GROQ_API_KEY is set, so every test here passes without
network access — the assertions check the contract (type, non-empty, no raise),
not the exact wording.
"""

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── Tool 1: search_listings ────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Impossible query — must return [] rather than raising.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=30)
    assert all(item["price"] <= 30 for item in results)


def test_search_size_filter_is_case_insensitive_substring():
    # "M" should match listings sized "M", "S/M", "M/L", etc.
    results = search_listings("vintage", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("graphic tee", size=None, max_price=None)
    # Top result should be a tops listing tagged as a graphic/band tee.
    assert results, "expected at least one match"
    assert "graphic tee" in results[0]["style_tags"] or "tee" in results[0]["title"].lower()


# ── Tool 2: suggest_outfit ──────────────────────────────────────────────────────

def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


def test_suggest_outfit_empty_wardrobe():
    # Empty wardrobe must still yield useful styling text, not a crash or "".
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


# ── Tool 3: create_fit_card ─────────────────────────────────────────────────────

def test_create_fit_card_returns_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("Pair it with baggy jeans and chunky sneakers.", item)
    assert isinstance(card, str)
    assert card.strip() != ""


def test_create_fit_card_empty_outfit():
    # Empty outfit must return a descriptive error string, not raise.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("", item)
    assert isinstance(card, str)
    assert card.strip() != ""
