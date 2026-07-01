# Sjakkfangst — Codebase Analysis Report

**Scope:** Security, Performance, Workflow, New Functionality
**Repo:** `torfinnnome/sjakkfangst` — Flask app scraping Lichess broadcasts for FIDE player games
**Date:** 2026-06-29

---

## 1. Security

### S1. DOM XSS via unescaped tournament/opening names — **High**
`templates/index.html:503` interpolates `t.name` (scraped from Lichess HTML) directly into `innerHTML`:
```js
li.innerHTML = `<a href="${href}" ... title="${t.name}"><span ...>${t.name}</span></a>`;
```
Same issue at `index.html:627-637` (opening names from PGN headers → `tr.innerHTML`) and `index.html:609` (`statsOverview.innerHTML` with `playerName` from PGN headers).

A tournament named `<img src=x onerror=alert(1)>` would execute. Lichess likely sanitizes, but the app must not trust external strings.
**Fix:** Build nodes via `document.createElement` + `textContent`, or escape with a helper (`str.replace(/[&<>"']/g, …)`). Add a `Content-Security-Policy` header (no `unsafe-inline`) as defense in depth.

### S2. Unbounded in-memory `tasks` dict — **High** (DoS)
`app.py:24` `tasks = {}` stores every fetch result forever (full PGN bytes per task_id). At 6 requests/min global cap → 8 640/day. Large players (e.g. Carlsen) yield MB-sized PGNs; the dict grows monotonically until OOM.
**Fix:** TTL eviction (e.g. `cachetools.TTLCache`), or persist task results to disk and serve via the existing cache module. Also means the app can't be horizontally scaled (see P11).

### S3. Flask dev server in production — **Medium**
`Containerfile:65` runs `python -m flask run`. Flask's built-in server is single-threaded, not hardened, and explicitly not for production. Combined with long-lived SSE connections, this is both a performance and a robustness/security concern.
**Fix:** Use `gunicorn` (with `--worker-class gevent` or `--worker-class eventlet` for SSE) or `waitress`. Pin in `requirements.txt`.

### S4. Missing security headers — **Medium**
No `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`. The app renders third-party-influenced content (tournament names, opening names).
**Fix:** Add `flask-talisman` or set headers in a `after_request` hook.

### S5. `parse_fide_url` accepts any FIDE ID/player slug — **Low** (SSRF largely mitigated)
The URL pattern is anchored (`^lichess\.org/fide/(\d+)/(\S+)$`), so the user can only target `lichess.org` paths. Downstream requests in `scraper.py` and `pgn_processor.py` construct URLs from `href.startswith("/broadcast/")` and a regex-captured `tournament_id`. Risk is low because all outbound calls go to `lichess.org`, but:
- The regex `r'"tour":\{"id":"([^"]+)"'` allows `/` in `tournament_id`, then it's interpolated into `https://lichess.org/api/broadcast/{tournament_id}.pgn`. Path traversal is contained (still hits `lichess.org`), but the URL could be malformed.
**Fix:** Validate `tournament_id` matches `^[A-Za-z0-9_-]+$` before constructing the API URL.

### S6. No CSRF protection on state-mutating GET — **Low**
`/fetch_stream` (GET) triggers scraping and stores results in `tasks`. `/download/<task_id>` (GET) returns file content. Combined with S2, a malicious page could embed `<img src="https://victim/fetch_stream?url=…">` to fill memory. The rate limiter per-IP mitigates, but a CSRF token or `SameSite` cookie would help.
**Fix:** Since this is GET-based, rely on rate limiting + an `Origin`/`Referer` check; consider POST for `/fetch_stream`.

### S7. PII in logs when `SJAKKFANGST_LOG_URLS=1` — **Low**
Full URLs including FIDE IDs and player names are written to stderr (journald). FIDE IDs are semi-public, but document this in a privacy section of the README.

### S8. `verify-security.sh` is host-trusting — **Informational**
The script only verifies a fixed set of container settings. It doesn't check for the missing security headers above, image vulnerability scanning, or that the image was rebuilt recently. Consider extending it or moving checks to CI.

---

## 2. Performance

### P1. Sequential tournament downloads with hardcoded `time.sleep(3)` — **High**
`app.py:92-152` downloads each tournament one at a time, sleeping 3 s between each. For 100 tournaments that's 5+ minutes of pure sleep plus network time, all on a single SSE worker.
**Fix:** Use a bounded `concurrent.futures.ThreadPoolExecutor` (e.g. 3–4 workers) with a semaphore-based rate limiter to stay within Lichess's allowances. Stream progress as futures complete.

### P2. Synchronous `requests` calls without `Session` — **Medium**
Every `requests.get` (in `_fetch_with_retry`, duplicated in `scraper.py:21` and `pgn_processor.py:22`) opens a new TCP connection. Lichess supports keep-alive.
**Fix:** Use a module-level `requests.Session` (per worker) to reuse connections. Also enables HTTP/2 via `httpx` if desired.

### P3. `_fetch_with_retry` retries on 4xx — **Medium**
`raise_for_status()` raises on 404/410, and the retry loop sleeps 2 s and retries — wasting Lichess's rate limit budget on permanent errors.
**Fix:** Only retry on `requests.ConnectionError`, `requests.Timeout`, and 5xx (`response.status_code >= 500`). Skip retries for 4xx.

### P4. PGN parsed twice per fetch — **Medium**
`filter_games_by_fide` (app.py:148) parses the PGN with `chess.pgn.read_game` in a loop; then `collect_opening_stats` (app.py:167) re-parses the *combined* filtered PGN. `chess.pgn.read_game` is expensive.
**Fix:** Single-pass function that returns both filtered PGN and stats, or cache the parsed game list on the first pass.

### P5. `_determine_tournament_status` re-runs regex over full PGN on every cache read — **Medium**
`cache.py:142` re-evaluates status from PGN text on every `get_cached_tournament` call, then rewrites metadata. For multi-MB PGNs this is O(n) disk + CPU on every hit.
**Fix:** Cache the computed status + end_date in metadata and only re-evaluate if `cached_at` is older than a short window (e.g. 1 hour) — once a tournament is `completed`, status doesn't change.

### P6. Uncompiled regex — **Low**
`_parse_tournament_end_date` (cache.py:47) and `download_broadcast_pgn` (pgn_processor.py:553) call `re.search` with string patterns on every call. Python caches recent patterns, but explicit `re.compile` at module level is clearer and avoids cache eviction churn.
**Fix:** Module-level `_DATE_RE = re.compile(r'\[Date "(\d{4})[.\-](\d{2})[.\-](\d{2})"\]')`.

### P7. `get_broadcasts` paginates serially with `time.sleep(1)` — **Medium**
`scraper.py:138-157` fetches up to ~5 pages sequentially. Total latency = 5 × (network + 1 s sleep).
**Fix:** Either prefetch page 2+ in parallel after parsing page 1's `next` link (still polite), or remove the sleep and rely on a global rate limiter for Lichess.

### P8. SSE generator holds a worker for the whole fetch — **High** (architecture)
A single fetch can run 5+ minutes. With Flask's dev server (S3) the whole app blocks for one user. Even with gunicorn, each worker is tied up for the duration.
**Fix:** Decouple scraping from SSE: enqueue a background job (thread/process), stream only progress events, store result in a shared backend (Redis or the existing disk cache) keyed by task_id. Multiple workers can then serve `/download/<task_id>`.

### P9. `ECO_OPENINGS` (500+ entries) loaded at import time — **Low**
Always loaded even when only downloading. ~15 KB, minor, but if the file grows it matters. Move to a lazy-loaded module or a JSON file read on demand.

### P10. Cache writes are non-atomic — **Low**
`cache.py:170` `pgn_path.write_text(pgn_text)` then `meta_path.write_text(...)`. A crash between the two writes leaves orphan PGN without metadata (handled gracefully on read), but a crash *during* `write_text` leaves a truncated file. Concurrent reads could see a half-written file.
**Fix:** Write to `*.tmp` then `os.replace()` for atomicity. Add file locking if concurrent writes are possible (currently single-worker, so low risk).

### P11. `tasks` dict breaks horizontal scaling — **Medium**
Same root as S2. If you add gunicorn workers (P8/S3) the in-memory dict is per-worker: a fetch on worker A, download on worker B → 404.
**Fix:** Move task results to disk (the cache module already has the infrastructure) or Redis.

### P12. No request/stream timeout — **Low**
The SSE response has no overall timeout. A slow/stuck client holds a worker indefinitely.
**Fix:** Add a max-duration guard in the generator; or rely on the reverse proxy (nginx) for `proxy_read_timeout`.

---

## 3. Workflow

### W1. No CI/CD — **High**
No `.github/workflows/`. Tests aren't run on push. CodeQL was run once manually (commit `2b0a03d`).
**Fix:** Add GitHub Actions: run `pytest`, `ruff check`, `ruff format --check`, and CodeQL on PRs. Build the container image as a CI step.

### W2. `pytest` in production image — **Medium**
`requirements.txt` includes `pytest`, so the runtime container carries test deps.
**Fix:** Split into `requirements.txt` (runtime) and `requirements-dev.txt` (or use a `pyproject.toml` with extras). Update Containerfile to install only runtime requirements.

### W3. No version pinning — **Medium**
All deps use `>=`. A new `flask` or `python-chess` release could break the app silently.
**Fix:** Pin versions (or generate a `requirements.lock`/`uv.lock`). python-chess especially has had breaking changes between minor versions.

### W4. `cache/` directory committed to repo — **Medium**
`ls cache/` shows `players/` and `tournaments/` subdirs in the repo. `.gitignore` only ignores `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
**Fix:** Add `cache/` to `.gitignore` (and remove from index if tracked). Verify with `git ls-files cache/`.

### W5. No `pyproject.toml` — **Low**
Modern Python projects use `pyproject.toml` for metadata, build system, ruff config, pytest config.
**Fix:** Add a `pyproject.toml` consolidating tool config (ruff, pytest) and project metadata.

### W6. No tests for `app.py` (HTTP layer) — **High**
Tests cover `cache.py`, `pgn_processor.py`, `rate_limit.py`, `scraper.py` — but not the Flask routes where the security issues live (S1, S2, S6).
**Fix:** Add `tests/test_app.py` using Flask's test client: assert rate-limit behavior, invalid URL handling, SSE stream events, download endpoint. This is the highest-value test gap.

### W7. Duplicated `_fetch_with_retry` — **Low**
Identical code in `scraper.py:16-28` and `pgn_processor.py:17-29`.
**Fix:** Extract to `http.py` (or extend `scraper.py`) and import from both. Single place to fix P3.

### W8. Inconsistent return type in `collect_opening_stats` — **Low** (latent bug)
`pgn_processor.py:659` returns `[]` on empty input, but the success path (line 785) returns `{"stats": ..., "player_name": ...}`. The caller (`app.py:167`) destructures `['stats']` and `['player_name']` — would `TypeError` on a list. Currently unreachable due to the `if not all_games` guard, but the contract is broken.
**Fix:** Return `{"stats": [], "player_name": ""}` consistently.

### W9. Redundant check in `app.py:115-118` — **Low** (code smell)
```python
if player_cached:
    if player_cached:  # always True
        p_hits += 1
        all_games.append(player_cached)
```
**Fix:** Drop the inner `if`.

### W10. No AGENTS.md / CONTRIBUTING.md — **Low**
Onboarding for new contributors (human or AI) is implicit.
**Fix:** Add `AGENTS.md` with build/test/lint commands, architecture summary, and conventions.

### W11. No ADRs / CONTEXT.md — **Low**
`docs/superpowers/` has specs and plans, but no Architecture Decision Records or a domain glossary. Decisions like "why disk cache vs Redis" or "why SSE vs WebSocket" aren't recorded.
**Fix:** Add `docs/adr/` and a `CONTEXT.md` (the `improve-codebase-architecture` skill explicitly looks for these).

### W12. No pre-commit hooks — **Low**
Ruff cache exists locally but isn't enforced pre-push.
**Fix:** Add `.pre-commit-config.yaml` with ruff + format.

### W13. README inconsistencies — **Low**
- README says "Tournament Cache: … cached for 24 hours (default)" but `CACHE_TTL_HOURS` default is 1 hour (Containerfile + cache.py).
- `run-rootless.sh --help` says "Cache TTL in hours (default: 24)" but the script defaults to 1.
**Fix:** Reconcile docs with code.

### W14. No container image CI / vulnerability scanning — **Medium**
Containerfile exists but isn't rebuilt in CI or scanned (e.g. `trivy`, `grype`).
**Fix:** Add a weekly CI job that builds and scans the image.

---

## 4. New Functionality (potential)

Ranked by value-to-effort ratio. Each is a vertical slice that can ship independently.

### F1. Player search by name — **High value, Low effort**
Currently requires a Lichess FIDE URL. Add a search box that queries `https://lichess.org/api/player/autocomplete?query=…` or scrapes the FIDE search page. Removes the manual "find the URL" step.

### F2. Game viewer / inline PGN replay — **High value, Medium effort**
Embed `chessground` (Lichess's board, MIT-licensed) or `cm-chessboard` to preview games inline before downloading. Click a row in the stats table → show that game's moves. Removes the "download to inspect" round-trip.

### F3. Opening repertoire tree — **High value, Medium effort**
Extend `collect_opening_stats` into a tree: for each opening, show the player's most common next move and win rate at depth 2-3. Like Lichess's opening explorer but scoped to the player's games. The data is already in the PGN; it's a richer view of the same stats.

### F4. Shareable deep links — **Medium value, Low effort**
`/player/<fide_id>/<name>` route that re-runs (or serves cached) fetch. Combine with the cache module's persistence so a link can be bookmarked. Currently results are ephemeral (and lost on restart due to S2).

### F5. Filters on the downloaded PGN — **Medium value, Low effort**
Before download, let the user exclude/include by tournament, result (W/D/L), opponent, ECO, or date range. The data is already filtered; this is just a UI + a re-filter pass.

### F6. Head-to-head and per-opponent stats — **Medium value, Medium effort**
Group games by opponent (already have `White`/`Black` headers). Show record, win rate, opening tendencies vs that opponent. Useful for player prep.

### F7. Export formats beyond PGN — **Low value, Low effort**
Add JSON and CSV export of the opening stats table (already structured data). One extra route, one serializer.

### F8. Charts — **Medium value, Medium effort**
Win rate by opening (bar), opponent Elo distribution (histogram), results over time (line). Can be done client-side with a tiny chart lib (Chart.js) or pure SVG.

### F9. Tournament status indicator in UI — **Low value, Low effort**
The cache already tracks `ongoing` vs `completed` per tournament. Surface it as a badge next to each row in the progress list.

### F10. Cache/admin page — **Low value, Low effort**
A `/admin` page (basic-auth gated) showing cache size, hit counts (`p/t/d` are already logged), and a "clear cache" button. Useful for operators.

### F11. RSS / "new tournament" subscription — **Medium value, High effort**
Poll Lichess for new broadcasts featuring a followed player; emit an RSS entry. Requires background scheduling (ties into P8's job-queue refactor).

### F12. API endpoint — **Low value, Low effort**
`/api/games/<fide_id>.pgn` and `/api/stats/<fide_id>.json` for programmatic access. Trivial once F4 is in place.

### F13. Mobile polish — **Low value, Low effort**
The stats table can overflow on narrow screens. Wrap it in a horizontally scrollable container or make it responsive.

---

## Top Recommendations (do these first)

1. **W6 + S1** — Add `tests/test_app.py` covering the HTTP layer; fix the DOM XSS while you're there. Highest leverage: tests catch regressions in the part of the codebase that has the most security surface and zero coverage.
2. **S2 + P8 + P11** — Move task results out of the in-memory `tasks` dict into the disk cache (or Redis). Unblocks horizontal scaling, fixes the OOM DoS, and is a prerequisite for adding gunicorn workers (S3).
3. **S3 + P1** — Replace Flask dev server with gunicorn (gevent/eventlet for SSE); parallelize tournament downloads with a bounded pool. Single change that addresses both the biggest perf and security concern.
4. **W1** — Add CI (pytest + ruff + CodeQL). Every other fix is safer with this in place.
5. **W4** — Untrack `cache/` from git. One-line fix; prevents accidental cache-data leaks in the repo.

## Quick wins (under 30 minutes each)
- W4: `.gitignore` + `git rm -r --cached cache/`
- W9: delete redundant `if player_cached:`
- W8: return `{"stats": [], "player_name": ""}` from `collect_opening_stats` on empty input
- W7: extract shared `_fetch_with_retry`
- P6: `re.compile` the date pattern at module level
- W13: fix README TTL inconsistency
- P3: skip retries on 4xx
