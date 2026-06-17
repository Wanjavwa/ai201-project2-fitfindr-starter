"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    # Step 2 — Parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3 — Search. This is the decision point of the planning loop:
    # an empty result short-circuits the run before any styling happens.
    session["search_results"] = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    if not session["search_results"]:
        bits = [f"No listings matched \"{parsed['description'] or query}\""]
        if parsed["size"]:
            bits.append(f"in size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:.0f}")
        session["error"] = (
            " ".join(bits)
            + ". Try removing the size filter, raising your budget, "
            "or describing the item differently."
        )
        return session  # do NOT proceed to suggest_outfit with empty input

    # Step 4 — Select the top (most relevant) result to carry forward.
    session["selected_item"] = session["search_results"][0]

    # Step 5 — Suggest an outfit for the selected item against the wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=session["wardrobe"],
    )

    # Step 6 — Turn the outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )

    # Step 7 — Return the completed session.
    return session


# ── query parsing ──────────────────────────────────────────────────────────────

# Recognized size tokens, longest first so "XXL" is matched before "XL"/"L".
_SIZE_TOKENS = ["XXS", "XXL", "XS", "XL", "S", "M", "L"]


def _parse_query(query: str) -> dict:
    """
    Extract a description, size, and max_price from a natural-language query.

    Uses lightweight regex (no LLM) so parsing is deterministic and free:
      - max_price: the first dollar amount after "under"/"below"/"$"
      - size:      a standalone size token (e.g. "size M", "in M")
      - description: the query with the price/size phrases stripped out

    Returns a dict with keys: description (str), size (str|None), max_price (float|None).
    """
    text = query.strip()
    lowered = text

    # max_price — "under $30", "below 30", "$30", "30 dollars"
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max|<)?\s*\$?\s*(\d+(?:\.\d{1,2})?)\s*(?:dollars|usd)?",
        lowered,
        flags=re.IGNORECASE,
    )
    if price_match and re.search(r"(?:under|below|less than|max|<|\$)", lowered, re.IGNORECASE):
        max_price = float(price_match.group(1))

    # size — "size M", "in size 8", "size: L"
    size = None
    size_phrase = re.search(
        r"\bsize[:\s]+([a-z0-9]+(?:\.\d)?)\b", lowered, flags=re.IGNORECASE
    )
    if size_phrase:
        size = size_phrase.group(1).upper()
    else:
        # Fall back to a standalone letter-size token surrounded by spaces.
        for tok in _SIZE_TOKENS:
            if re.search(rf"\bsize\s+{tok}\b|\bin\s+{tok}\b", lowered, re.IGNORECASE):
                size = tok
                break

    # description — strip the size/price phrases so they don't pollute keywords.
    description = re.sub(
        r"(?:under|below|less than|max)?\s*\$?\s*\d+(?:\.\d{1,2})?\s*(?:dollars|usd)?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    description = re.sub(
        r"\bsize[:\s]+[a-z0-9]+(?:\.\d)?\b", "", description, flags=re.IGNORECASE
    ).strip()
    description = re.sub(r"\s{2,}", " ", description)

    return {"description": description, "size": size, "max_price": max_price}


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    # Fit cards contain emoji; make the console print them on Windows (cp1252).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
