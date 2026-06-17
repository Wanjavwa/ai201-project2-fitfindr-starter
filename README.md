# FitFindr 🛍️

A multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it. Describe what you're after in plain language; FitFindr searches a mock listings dataset, styles the best find against your wardrobe, and writes a shareable outfit caption — handling the cases where a tool finds nothing or fails.

Built for AI201 Project 2.

---

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (Git Bash):**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file in the repo root (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## Running it

```bash
python app.py          # launch the Gradio UI (open the URL it prints)
python agent.py        # run the two built-in CLI test cases (happy path + no-results)
pytest tests/          # run the tool test suite
```

> **Windows note:** fit cards contain emoji. `agent.py` reconfigures stdout to UTF-8 so `python agent.py` prints them fine. For ad-hoc `python -c "..."` snippets that print fit cards, prefix with `PYTHONUTF8=1` (Git Bash) or run `chcp 65001` first.

---

## How the agent works

FitFindr runs a **state-driven planning loop** in [`agent.py`](agent.py). It isn't a fixed pipeline that always fires all three tools — each step's result decides whether the next one runs. The single source of truth is a `session` dict created by `_new_session()`; every tool reads from it and writes its output back.

```
User query + wardrobe choice
        │
        ▼
  _parse_query  →  session["parsed"] = {description, size, max_price}
        │
        ▼
  search_listings(**parsed)  →  session["search_results"]
        │
        ├─ results == []  →  set session["error"], RETURN EARLY   ◄── error branch
        │                     (suggest_outfit is never called)
        │
        ├─ results != []  →  session["selected_item"] = results[0]
        │                         │
        │                         ▼
        │                   suggest_outfit(selected_item, wardrobe)
        │                         │  →  session["outfit_suggestion"]
        │                         ▼
        │                   create_fit_card(outfit_suggestion, selected_item)
        │                         │  →  session["fit_card"]
        ▼                         ▼
              return session  →  app.py maps it to 3 UI panels
```

### Planning loop logic (the actual branches)

1. **Parse.** `_parse_query()` uses regex (no LLM, so it's deterministic and free) to pull a `description`, `size`, and `max_price` out of the natural-language query.
2. **Search.** Call `search_listings(**parsed)`. **This is the decision point:** if it returns `[]`, the loop writes a specific message to `session["error"]` and returns immediately — it does **not** continue to styling with empty input. If it returns matches, the top one becomes `session["selected_item"]`.
3. **Suggest.** Call `suggest_outfit(selected_item, wardrobe)`. The tool branches internally on whether the wardrobe has items (named-piece outfits vs. general styling advice).
4. **Fit card.** Call `create_fit_card(outfit_suggestion, selected_item)`.
5. **Done** when `fit_card` is set, or earlier if step 2 set `error`.

The agent's behavior demonstrably differs by input: an impossible query short-circuits after one tool call, while a matchable query runs all three.

### State management

All cross-tool state lives in the `session` dict — no globals, no re-prompting the user between steps:

| Key | Written by | Read by |
|-----|-----------|---------|
| `query` | `_new_session` | `_parse_query` |
| `parsed` | parse step | `search_listings` |
| `search_results` | `search_listings` | selection step |
| `selected_item` | selection step | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | `app.py` |
| `error` | any failing step | `app.py` (checked first) |

The listing found by `search_listings` flows into `suggest_outfit` and then `create_fit_card` purely through `session["selected_item"]` — the user never re-enters the item.

---

## Tool Inventory

Signatures match [`tools.py`](tools.py) exactly.

### `search_listings(description, size, max_price) -> list[dict]`
- **Purpose:** Search the 40-item mock dataset and rank matches. Pure Python (no LLM) for speed and determinism.
- **Inputs:**
  - `description` (`str`) — free-text keywords, e.g. `"vintage graphic tee"`. Tokenized and matched against each listing's title, description, and `style_tags`.
  - `size` (`str | None`) — size filter, matched case-insensitively as a substring so `"M"` matches `"S/M"`, `"M/L"`. `None` skips the filter.
  - `max_price` (`float | None`) — inclusive price ceiling. `None` skips the filter.
- **Returns:** `list[dict]` of full listing dicts (`id, title, description, category, style_tags, size, condition, price, colors, brand, platform`), sorted by keyword-overlap relevance, highest first. Returns `[]` when nothing matches — never raises.

### `suggest_outfit(new_item, wardrobe) -> str`
- **Purpose:** Ask the LLM to style one item against the user's wardrobe.
- **Inputs:**
  - `new_item` (`dict`) — a single listing dict (normally `session["selected_item"]`).
  - `wardrobe` (`dict`) — a dict with an `"items"` list of wardrobe-item dicts; may be empty.
- **Returns:** A non-empty `str`. With a populated wardrobe it names actual pieces; with an empty wardrobe it returns general styling advice.

### `create_fit_card(outfit, new_item) -> str`
- **Purpose:** Turn the outfit into a short, casual, shareable caption (LLM, `temperature=1.0` so it varies run-to-run).
- **Inputs:**
  - `outfit` (`str`) — the styling text from `suggest_outfit`.
  - `new_item` (`dict`) — the selected listing dict (used to mention name, price, platform).
- **Returns:** A 2–4 sentence caption `str`. If `outfit` is empty/whitespace, returns a descriptive error string instead of raising.

**Model:** `llama-3.3-70b-versatile` via Groq, for both LLM-backed tools.

---

## Interaction Walkthrough

**User query:** `"looking for a vintage graphic tee under $30"` (Example wardrobe selected)

**Step 1 — Tool called: `search_listings`**
- Input: `_parse_query` produces `description="looking for a vintage graphic tee"`, `size=None`, `max_price=30.0`; the loop calls `search_listings("looking for a vintage graphic tee", size=None, max_price=30.0)`.
- Why this tool: every run starts with search — there's nothing to style until we have an item.
- Output: a relevance-sorted list of tops tagged `graphic tee` / `vintage` under $30. The loop checks it's non-empty and sets `selected_item = results[0]`.

**Step 2 — Tool called: `suggest_outfit`**
- Input: `suggest_outfit(new_item=<selected tee>, wardrobe=<example wardrobe>)`.
- Why this tool: we have an item and a non-empty wardrobe, so the loop proceeds to styling.
- Output: e.g. *"Pair it with your Baggy straight-leg jeans and Chunky white sneakers; layer the Vintage black denim jacket over the top for a 90s streetwear look."* Stored in `session["outfit_suggestion"]`.

**Step 3 — Tool called: `create_fit_card`**
- Input: `create_fit_card(outfit=<that suggestion>, new_item=<selected tee>)`.
- Why this tool: an outfit exists, so we generate the shareable caption.
- Output: e.g. *"thrifted this faded tee off depop for $24 and it was made for my baggy jeans 🖤 full fit in stories."* Stored in `session["fit_card"]`.

**Final output to user:** Three UI panels — the top listing's details, the outfit idea, and the fit card.

**Error path:** for `"designer ballgown size XXS under $5"`, `search_listings` returns `[]`; the loop sets `session["error"]` and returns. Only the first panel shows the message (*"No listings matched 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your budget, or describing the item differently."*); the other two stay empty, and `suggest_outfit`/`create_fit_card` are never called.

---

## Error Handling and Fail Points

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listings match the filters (returns `[]`) | Loop sets a specific `session["error"]` naming what was searched and how to loosen it, then returns early — `suggest_outfit` is **not** called. |
| `suggest_outfit` | Empty wardrobe; or LLM/network error | Empty wardrobe → switches to a general-styling-advice prompt and still returns useful text. LLM error → caught, returns a plain fallback styling string so the run continues. |
| `create_fit_card` | Empty/whitespace `outfit`; or LLM/network error | Empty outfit → returns a descriptive error string (no raise). LLM error → caught, returns a simple caption built from the item's name/price/platform. |

**Concrete example from testing:** running `search_listings('designer ballgown', size='XXS', max_price=5)` returns `[]` (verified in `tests/test_tools.py::test_search_empty_results`). Running the full agent on that query produces `session["error"] = "No listings matched \"designer ballgown\" in size XXS under $5. Try removing the size filter..."` and leaves `session["fit_card"]` as `None` — confirmed via `python agent.py`.

---

## Spec Reflection

> _Draft below based on how the build actually went — review and rewrite in your own voice before submitting._

**One way planning.md helped during implementation:**
Writing the State Management table before any code meant the `session` dict had a fixed contract — each tool knew exactly which key to read and which to write. When wiring the planning loop, there was no guesswork about how the found item reached `suggest_outfit`; it was just `session["selected_item"]`, exactly as specified.

**One divergence from your spec, and why:**
The spec left query parsing open ("regex, string splitting, or the LLM"). I committed to a regex parser (`_parse_query`) rather than an LLM call, because parsing `size`/`max_price` is a solved deterministic problem and avoiding an extra LLM round-trip keeps the agent faster, free, and easier to test.

---

## AI Usage

> _These two instances reflect this build. Confirm they match what you actually did and adjust before submitting._

**Instance 1 — implementing the tools (Milestone 3).**
- **Input:** the per-tool spec blocks from `planning.md` (inputs, return value, failure mode) plus the existing stubs and docstrings in `tools.py`, one tool at a time.
- **Produced:** implementations of `search_listings` (keyword scoring + size/price filters), `suggest_outfit`, and `create_fit_card`, using `load_listings()` and the scaffolded Groq client.
- **What I changed/overrode:** added a stopword list so filler words ("looking", "for") didn't inflate relevance scores; weighted `style_tags` hits higher than title/description; and wrapped both LLM calls in try/except fallbacks so a missing key or network error degrades gracefully instead of crashing the agent.

**Instance 2 — wiring the planning loop (Milestone 4).**
- **Input:** the Planning Loop + State Management sections and the architecture diagram from `planning.md`, plus the `run_agent` stub.
- **Produced:** the `run_agent` loop with the early-return error branch, and `handle_query` in `app.py`.
- **What I changed/overrode:** confirmed the loop branches on the search result (not an unconditional 3-tool sequence) and verified state flow with `python agent.py`; added a UTF-8 stdout reconfigure in the CLI block after hitting a Windows cp1252 crash printing emoji.

---

## Tests

`tests/test_tools.py` covers each tool's happy path and documented failure mode (no results, empty wardrobe, empty outfit). The LLM tools fall back to a non-empty string when no API key is set, so the suite passes offline — it checks the contract (type, non-empty, no raise), not exact wording.

```bash
pytest tests/
```
