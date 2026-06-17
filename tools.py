"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Model used for the two LLM-backed tools (suggest_outfit, create_fit_card).
_MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    keywords = _tokenize(description)

    scored = []
    for item in listings:
        # Filter: price ceiling (inclusive).
        if max_price is not None and item["price"] > max_price:
            continue
        # Filter: size, case-insensitive substring so "M" matches "S/M", "M/L".
        if size is not None and size.strip().lower() not in item["size"].lower():
            continue
        # Score: keyword overlap against title, description, and style_tags.
        score = _relevance_score(keywords, item)
        if score == 0:
            continue
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# Words that add no matching signal — ignored when scoring relevance.
_STOPWORDS = {
    "a", "an", "the", "for", "with", "and", "or", "in", "of", "to", "on",
    "i", "im", "looking", "want", "need", "some", "find", "me", "my",
    "size", "under", "over", "that", "this", "is", "are", "it",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into meaningful word tokens."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def _relevance_score(keywords: list[str], item: dict) -> int:
    """
    Count how many query keywords appear in a listing's searchable text.
    style_tag hits are weighted slightly higher since tags are curated.
    """
    title_desc = f"{item['title']} {item['description']}".lower()
    tags = " ".join(item.get("style_tags", [])).lower()
    score = 0
    for kw in keywords:
        if kw in tags:
            score += 2
        elif kw in title_desc:
            score += 1
    return score


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item['title']} — {new_item.get('category', 'item')}, "
        f"colors: {', '.join(new_item.get('colors', []))}, "
        f"style: {', '.join(new_item.get('style_tags', []))}."
    )
    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe: ask for general styling advice instead of named pieces.
        prompt = (
            f"A shopper is considering this secondhand item:\n{item_desc}\n\n"
            "They have not entered any wardrobe pieces yet. Suggest one or two "
            "complete outfit ideas built around this item: what kinds of pieces "
            "pair well, what vibe it suits, and a styling tip. Keep it to 3-4 "
            "sentences and don't assume specific items they own."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it.get('category', '')}; "
            f"{', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            f"A shopper is considering this secondhand item:\n{item_desc}\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest one or two complete outfits that pair this new item with "
            "specific pieces from their wardrobe, naming the pieces exactly. "
            "Add a short styling tip. Keep it to 3-4 sentences."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        text = response.choices[0].message.content.strip()
        if text:
            return text
        # Empty completion is itself a failure — fall through to the fallback.
        raise ValueError("empty completion")
    except Exception:
        # Network/API failure: degrade gracefully so the loop can still continue.
        return (
            f"Style the {new_item['title']} as the statement piece: keep the rest "
            f"of the outfit simple and let its {', '.join(new_item.get('colors', [])) or 'colors'} "
            "stand out. (Live styling suggestions are unavailable right now.)"
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no outfit means there's nothing to caption.
    if not outfit or not outfit.strip():
        return (
            "Couldn't create a fit card — no outfit suggestion was provided. "
            "Try styling the item first."
        )

    price = new_item.get("price")
    prompt = (
        "Write a short, casual social-media caption (2-4 sentences) for an "
        "outfit-of-the-day post about a thrifted find. Make it sound like a real "
        "person posting, not a product description.\n\n"
        f"Item: {new_item['title']}\n"
        f"Price: ${price}\n"
        f"Platform: {new_item.get('platform', 'a resale app')}\n"
        f"Outfit: {outfit}\n\n"
        "Mention the item name, price, and platform naturally — once each. "
        "Capture the vibe of the outfit in specific terms. Emojis are welcome "
        "but keep it to one or two."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,  # high temperature so captions vary across runs
            max_tokens=160,
        )
        text = response.choices[0].message.content.strip()
        if text:
            return text
        raise ValueError("empty completion")
    except Exception:
        return (
            f"thrifted this {new_item['title']} off "
            f"{new_item.get('platform', 'a resale app')} for ${price} ✨ "
            "obsessed with how it pulls the whole look together. "
            "(Live caption generation is unavailable right now.)"
        )
