# Player Search by Name Design

## Overview

Add autocomplete search to the input field so users can type a player name instead of pasting a full FIDE URL. Search scrapes Lichess's FIDE player directory (`/fide?q=...`) and extracts matching players with their FIDE IDs.

## Goals

- Remove the manual "find the URL" step for users who know the player's name.
- Preserve the existing URL-paste workflow unchanged.
- Avoid spamming Lichess with requests — use debounce and caching.

## Architecture

### Backend: `/search` endpoint

New `GET /search?q=<query>` route in `app.py`:

1. Trim whitespace and lowercase the query. Reject if `len(q) < 2` (returns empty array immediately; covers empty and whitespace-only input).
2. Check disk cache at `cache/search/<md5(query)>` — return cached results on hit. Cache is permanent (player→FIDE mapping doesn't change).
3. On cache miss:
   - URL-encode the query for safety.
   - Fetch `https://lichess.org/fide?q=<query>` via `http_client.fetch_with_retry`.
   - Parse HTML with BeautifulSoup, extract all `href="/fide/{fide_id}/{slug}"` links. For each link, extract the display name from the adjacent `.player-intro__name` element (text content, stripped of title spans like "GM").
   - Deduplicate by FIDE ID (keep first occurrence), then cap at 10 results.
   - Cache results as JSON: `{query, results, cached_at}`.
   - Return results as JSON array: `[{fideId, slug, name}]`.
4. If HTML parsing fails (e.g., Lichess page redesign), return empty array and log the error — never return 500.
5. Search has its own rate limiter: 1 request per 5s per IP (separate from the main `/fetch_stream` limiter which is 2 per 60s). This prevents search from consuming the user's budget for the main feature.
6. No CSRF required — read-only endpoint.

### Frontend: Autocomplete dropdown

Single input field, dual-mode:

- Label: "Player URL or Name"
- Placeholder: `carlsen` or `https://lichess.org/fide/1503014/...`
- On `input` event: cancel any pending fetch, then 1500ms debounce → fetch `/search?q=...` via `fetch()`.
- If input starts with `http` (case-insensitive), skip search entirely (URL paste mode, existing behavior).
- Mode switching: if the user backspaces from a URL to a name, search re-triggers on the next input event (no `http` prefix → search mode). Conversely, pasting a URL while the dropdown is open hides the dropdown immediately.
- Dropdown appears below input with matching players (name + FIDE ID).
- Click dropdown item → input fills with full FIDE URL `https://lichess.org/fide/{fideId}/{slug}`, dropdown hides.
- Dropdown hides on click outside (document-level `click` listener) or on form submit.
- Keyboard navigation: `ArrowDown`/`ArrowUp` cycles highlighted item, `Enter` selects highlighted item, `Escape` dismisses dropdown.
- ARIA: dropdown uses `role="listbox"`, items use `role="option"`, input uses `aria-autocomplete="list"` and `aria-controls` pointing to dropdown.
- Form submission with partial name: existing `/fetch_stream` handler returns an error (invalid URL), user sees standard error message. Client-side validation: if input doesn't match `lichess.org/fide/` and dropdown is open, show "Please select a player from the list" before submit.
- Form submission unchanged: submits to `/fetch_stream`.

### Cache

- Location: `cache/search/<md5(query)>.json`
- No TTL — player to FIDE ID mapping is effectively permanent.
- Atomic writes via existing `_atomic_write` pattern (write to `.tmp` then `os.replace`).
- `cache/search/` directory created with `os.makedirs(..., exist_ok=True)` before any cache write attempt (at module import time).
- Cache grows unbounded — deferred: if this runs for years, add a max-file count cleanup.

### Error Handling

- Lichess returns non-200 or connection times out → return empty array, no cache write.
- HTML parsing fails (unexpected structure) → return empty array, log error, no cache write.
- Backend returns 429 (rate limited) → error text displays below input: "Search rate limited, please wait" (same styling as existing error text, disappears on next input event).
- Frontend `fetch()` network error → hide dropdown, show error text: "Search unavailable".
- `http_client.fetch_with_retry` does not retry on 4xx (existing behavior), so 429 is returned immediately.

### Testing

- `tests/test_app.py`: test `/search` endpoint with mocked `http_client._session.get`.
- Test cache hit/miss behavior.
- Test short query (< 2 chars) returns empty array without Lichess calls.
- Test URL-paste mode still works (no search triggered).
- Test deduplication of FIDE IDs.
- Test result cap (max 10 results after dedup).
- Test HTML parse failure returns empty array, not 500.
- Test cached file JSON structure matches expected format.
- Test search rate limiter is independent of main rate limiter.
- Frontend tests intentionally omitted — dropdown behavior is DOM manipulation, not business logic, and the project has no frontend test infrastructure.
