# F1 Player Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add autocomplete search so users can type a player name instead of pasting a FIDE URL.

**Architecture:** Backend `/search` endpoint scrapes Lichess FIDE directory (`lichess.org/fide?q=...`), caches results permanently in `CACHE_DIR/search/`, returns JSON array of `{fide_id, name, slug}`. Frontend adds debounced dropdown with keyboard navigation and ARIA attributes. Short queries (< 2 chars) return empty immediately without cache or network.

**Tech Stack:** Flask, BeautifulSoup4, requests, vanilla JS, CSS.

---

### Task 1: Add search cache functions to `cache.py`

**Files:**
- Modify: `cache.py` (append after line 342)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py` a new test class:

```python
class TestSearchCache:
    def test_get_cached_search_miss(self, temp_cache_dir):
        assert cache.get_cached_search("carlsen") is None

    def test_round_trip(self, temp_cache_dir):
        results = [
            {"fide_id": "1503014", "name": "Carlsen, Magnus", "slug": "MagnusCarlsen"},
            {"fide_id": "1001234", "name": "Carlsen, John", "slug": "JohnCarlsen"},
        ]
        cache.cache_search("carlsen", results)
        cached = cache.get_cached_search("carlsen")
        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["fide_id"] == "1503014"

    def test_cache_is_permanent(self, temp_cache_dir, monkeypatch):
        results = [{"fide_id": "1503014", "name": "Carlsen, Magnus", "slug": "MagnusCarlsen"}]
        cache.cache_search("carlsen", results)
        # Even after a long time, search cache never expires
        monkeypatch.setattr(cache, "CACHE_TTL_HOURS", 0)
        cached = cache.get_cached_search("carlsen")
        assert cached is not None
        assert len(cached) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py::TestSearchCache -v`
Expected: FAIL with "get_cached_search not defined" or similar import error.

- [ ] **Step 3: Write implementation**

Append to `cache.py` after line 342:

```python

def get_cached_search(query: str) -> Optional[list]:
    """Get cached search results for a player name query.

    Search results are cached permanently (no TTL) since FIDE player data
    changes infrequently.

    Args:
        query: The search query string (case-insensitive).

    Returns:
        Cached list of player dicts if found, None otherwise.
    """
    hash_key = hashlib.md5(query.lower().encode()).hexdigest()[:16]
    search_dir = Path(CACHE_DIR) / "search"
    json_path = search_dir / f"{hash_key}.json"

    if not json_path.exists():
        return None

    try:
        return json.loads(json_path.read_text())
    except (json.JSONDecodeError, IOError):
        return None


def cache_search(query: str, results: list) -> None:
    """Cache search results for a player name query.

    Args:
        query: The search query string.
        results: List of player dicts with 'fide_id', 'name', 'slug' keys.
    """
    try:
        hash_key = hashlib.md5(query.lower().encode()).hexdigest()[:16]
        search_dir = Path(CACHE_DIR) / "search"
        json_path = search_dir / f"{hash_key}.json"

        search_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(json_path, json.dumps(results))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write search cache: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py::TestSearchCache -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cache.py tests/test_app.py
git commit -m "feat: add search cache functions to cache.py"
```

---

### Task 2: Add `SearchRateLimiter` class to `rate_limit.py`

**Files:**
- Modify: `rate_limit.py` (append after line 61)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
class TestSearchRateLimiter:
    def test_allows_first_request(self):
        from rate_limit import SearchRateLimiter
        limiter = SearchRateLimiter()
        allowed, _ = limiter.check("127.0.0.1")
        assert allowed is True

    def test_blocks_second_request_within_window(self):
        from rate_limit import SearchRateLimiter
        limiter = SearchRateLimiter()
        limiter.check("127.0.0.1")
        allowed, _ = limiter.check("127.0.0.1")
        assert allowed is False

    def test_allows_after_window_expires(self, monkeypatch):
        from rate_limit import SearchRateLimiter
        import time as time_module
        limiter = SearchRateLimiter()
        limiter.check("127.0.0.1")
        monkeypatch.setattr(time_module, "time", lambda: time_module.time() + 6)
        allowed, _ = limiter.check("127.0.0.1")
        assert allowed is True

    def test_different_ips_are_independent(self):
        from rate_limit import SearchRateLimiter
        limiter = SearchRateLimiter()
        limiter.check("127.0.0.1")
        allowed, _ = limiter.check("192.168.1.1")
        assert allowed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py::TestSearchRateLimiter -v`
Expected: FAIL with "SearchRateLimiter not defined"

- [ ] **Step 3: Write implementation**

Append to `rate_limit.py` after line 61:

```python

SEARCH_MAX_REQUESTS = 1
SEARCH_WINDOW_SECONDS = 5


class SearchRateLimiter:
    """Track search request timestamps and enforce per-IP rate limits.

    Allows 1 search request per 5 seconds per IP address. Uses the same
    sliding-window pattern as RateLimiter but with tighter limits since
    each search triggers an external scrape.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ip_times: dict[str, list[float]] = {}

    def _prune(self, times: list[float], now: float) -> list[float]:
        return [t for t in times if now - t < SEARCH_WINDOW_SECONDS]

    def check(self, client_ip: str) -> Tuple[bool, float]:
        """Check whether a search request from client_ip is allowed.

        Returns:
            (allowed, wait_seconds)
            - allowed: True if request can proceed
            - wait_seconds: 0 if allowed, or seconds until next slot opens
        """
        now = time.time()

        with self._lock:
            ip_times = self._ip_times.get(client_ip, [])
            ip_times = self._prune(ip_times, now)
            self._ip_times[client_ip] = ip_times

            if len(ip_times) >= SEARCH_MAX_REQUESTS:
                oldest = min(ip_times)
                wait = SEARCH_WINDOW_SECONDS - (now - oldest)
                return False, max(wait, 0)

            ip_times.append(now)
            return True, 0.0


_search_limiter = SearchRateLimiter()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py::TestSearchRateLimiter -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add rate_limit.py tests/test_app.py
git commit -m "feat: add SearchRateLimiter class with 1 req/5s per IP"
```

---

### Task 3: Add `/search` endpoint and `search_fide_players()` to `app.py`

**Files:**
- Modify: `app.py` (add imports at top, add function + route before `if __name__`)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py`:

```python
import requests as requests_lib


class TestSearchEndpoint:
    def test_short_query_returns_empty(self, client):
        r = client.get("/search?q=a")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_empty_query_returns_empty(self, client):
        r = client.get("/search?q=")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_scraper_and_caching_flow(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        monkeypatch.setattr(app_module, "_search_limiter", rate_limit.SearchRateLimiter())

        mock_html = """
        <div class="player-search-result">
          <a href="/fide/1503014/MagnusCarlsen" class="player-search-result__link">
            <span class="player-intro__name">Carlsen, Magnus</span>
          </a>
        </div>
        <div class="player-search-result">
          <a href="/fide/1001234/HikaruNakamura" class="player-search-result__link">
            <span class="player-intro__name">Nakamura, Hikaru</span>
          </a>
        </div>
        """

        mock_response = requests_lib.Response()
        mock_response._content = mock_html.encode()
        mock_response.status_code = 200

        with patch("app.fetch_with_retry", return_value=mock_response):
            r = client.get("/search?q=carl")

        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["fide_id"] == "1503014"
        assert data[0]["name"] == "Carlsen, Magnus"
        assert data[0]["slug"] == "MagnusCarlsen"

    def test_cache_hit_returns_cached(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        monkeypatch.setattr(app_module, "_search_limiter", rate_limit.SearchRateLimiter())

        cache.cache_search("test", [{"fide_id": "999", "name": "Test, Player", "slug": "TestPlayer"}])

        r = client.get("/search?q=test")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["fide_id"] == "999"

    def test_rate_limiting_returns_429(self, client, temp_cache_dir, monkeypatch):
        monkeypatch.setattr(app_module, "_search_limiter", rate_limit.SearchRateLimiter())

        mock_html = '<div class="player-search-result"><a href="/fide/1/x"><span class="player-intro__name">A</span></a></div>'
        mock_response = requests_lib.Response()
        mock_response._content = mock_html.encode()
        mock_response.status_code = 200

        with patch("app.fetch_with_retry", return_value=mock_response):
            r1 = client.get("/search?q=test")
            assert r1.status_code == 200

            r2 = client.get("/search?q=test")
            assert r2.status_code == 429

    def test_error_handling_returns_500(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        monkeypatch.setattr(app_module, "_search_limiter", rate_limit.SearchRateLimiter())

        with patch("app.fetch_with_retry", side_effect=requests_lib.RequestException("fail")):
            r = client.get("/search?q=test")

        assert r.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py::TestSearchEndpoint -v`
Expected: FAIL with 404 or function not defined

- [ ] **Step 3: Write implementation**

Update the Flask import on line 12:

```python
from flask import Flask, request, send_file, Response, render_template, jsonify
```

Add after line 12 (new import lines):

```python
from bs4 import BeautifulSoup
from urllib.parse import quote
```

Update the `from cache import` block (lines 20-23):

```python
from cache import (
    get_cached_player, cache_player, get_cached_tournament, cache_tournament,
    _get_hash, _get_metadata_path, cache_task, get_cached_task,
    get_cached_search, cache_search,
)
```

Update the `from rate_limit import` line (line 24):

```python
from rate_limit import rate_limiter, _search_limiter
```

Add after line 25 (new import):

```python
from http_client import fetch_with_retry
```

Add the `search_fide_players` function and `/search` route before the `if os.environ.get` block (around line 276):

```python
def search_fide_players(query: str) -> list:
    """Scrape Lichess FIDE directory for players matching the query.

    Args:
        query: Player name search term.

    Returns:
        List of dicts with 'fide_id', 'name', 'slug' keys.

    Raises:
        requests.RequestException on network failures.
    """
    url = f"https://lichess.org/fide?q={quote(query)}"
    response = fetch_with_retry(url, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    for item in soup.find_all("div", class_="player-search-result"):
        link = item.find("a", class_="player-search-result__link", href=True)
        name_span = item.find("span", class_="player-intro__name")
        if not link or not name_span:
            continue

        href = link["href"]
        match = re.match(r"^/fide/(\d+)/(\S+)$", href)
        if not match:
            continue

        fide_id = match.group(1)
        slug = match.group(2)
        name = name_span.get_text(strip=True)

        results.append({
            "fide_id": fide_id,
            "name": name,
            "slug": slug,
        })

    return results


@app.route("/search", methods=["GET"])
def search():
    """Search for FIDE players by name. Returns JSON array of matches.

    Results are cached permanently. Rate limited to 1 request per 5s per IP.
    Queries shorter than 2 characters return empty immediately.
    """
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return jsonify([])

    cached = get_cached_search(query)
    if cached is not None:
        return jsonify(cached)

    client_ip = request.remote_addr
    allowed, wait = _search_limiter.check(client_ip)
    if not allowed:
        return jsonify({"error": "rate_limited", "wait": int(wait) + 1}), 429

    try:
        results = search_fide_players(query)
    except Exception:
        logging.getLogger(__name__).exception("Search failed for query: %s", query)
        return jsonify({"error": "search failed"}), 500

    cache_search(query, results)
    return jsonify(results)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py::TestSearchEndpoint -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add /search endpoint with scraping, caching, and rate limiting"
```

---

### Task 4: Update `templates/index.html`

**Files:**
- Modify: `templates/index.html` (lines 12-27)
- Test: Manual verification in browser

- [ ] **Step 1: Update the HTML**

Replace lines 12-27 of `templates/index.html` with:

```html
        <p class="description">
            Enter a <a href="https://lichess.org/fide" target="_blank">Lichess FIDE player URL</a> to download all games from that player's broadcast tournaments.
        </p>

        <form id="fetch-form">
            <label for="url">Player Name or Lichess FIDE URL</label>
            <div class="search-wrapper">
                <input
                    type="text"
                    id="url"
                    name="url"
                    placeholder="Search player name or paste FIDE URL"
                    required
                    autofocus
                    autocomplete="off"
                    aria-autocomplete="list"
                    aria-controls="searchResults"
                    aria-expanded="false"
                    aria-activedescendant=""
                >
                <div id="searchResults" role="listbox" aria-label="Player search results"></div>
            </div>
            <button type="submit" id="submit-btn">Fetch Games</button>
        </form>
```

Key changes:
- Change input type from `url` to `text` to allow name search
- Update label to mention both name and URL
- Update placeholder text
- Wrap input in `.search-wrapper` div for positioning
- Add `#searchResults` div with `role="listbox"`
- Add ARIA attributes: `aria-autocomplete`, `aria-controls`, `aria-expanded`, `aria-activedescendant`
- Add `autocomplete="off"` to prevent browser autocomplete interfering

- [ ] **Step 2: Verify in browser**

Open the page and verify:
- Input accepts both text and URLs
- Placeholder text is correct
- Search results container is hidden by default (handled by CSS)

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: update form for player name search with ARIA attributes"
```

---

### Task 5: Add dropdown CSS to `static/style.css`

**Files:**
- Modify: `static/style.css` (append after line 302)
- Test: Manual verification in browser

- [ ] **Step 1: Add CSS**

Append to `static/style.css` after line 302:

```css
.search-wrapper {
    position: relative;
    width: 100%;
}

#searchResults {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    max-height: 240px;
    overflow-y: auto;
    background: white;
    border: 1px solid #ddd;
    border-radius: 0 0 4px 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    z-index: 100;
    display: none;
}

#searchResults.visible {
    display: block;
}

.search-result {
    padding: 10px 12px;
    cursor: pointer;
    border-bottom: 1px solid #f0f0f0;
    font-size: 14px;
    color: #333;
}

.search-result:last-child {
    border-bottom: none;
}

.search-result:hover,
.search-result.active {
    background-color: #f0f9f4;
    color: #369962;
}

.search-result .player-name {
    font-weight: 600;
}

.search-result .player-fide {
    font-size: 12px;
    color: #999;
    margin-left: 8px;
}

.search-no-results {
    padding: 10px 12px;
    color: #999;
    font-size: 14px;
    font-style: italic;
}

input[type="text"] {
    padding: 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 16px;
    width: 100%;
    box-sizing: border-box;
}

input[type="text"]:focus {
    outline: none;
    border-color: #369962;
}
```

- [ ] **Step 2: Verify in browser**

Verify dropdown renders correctly with proper styling, hover states,
and active item highlighting. Dropdown should not overlap other elements.

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat: add search dropdown styles to style.css"
```

---

### Task 6: Add search JS to `static/app.js`

**Files:**
- Modify: `static/app.js` (append after line 324)
- Test: Manual verification in browser

- [ ] **Step 1: Add JavaScript**

Append to `static/app.js` after line 324:

```javascript
// Search autocomplete elements
const searchResults = document.getElementById('searchResults');
let searchTimeout = null;
let activeSearchIndex = -1;
let currentSearchResults = [];

function isUrl(str) {
    return /^(https?:\/\/)?lichess\.org\/f\/ide\//i.test(str);
}

function debounceSearch(value) {
    if (searchTimeout) {
        clearTimeout(searchTimeout);
    }
    if (isUrl(value) || value.length < 2) {
        hideSearchDropdown();
        return;
    }
    searchTimeout = setTimeout(function() {
        fetch("/search?q=" + encodeURIComponent(value))
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (Array.isArray(data)) {
                    currentSearchResults = data;
                    activeSearchIndex = -1;
                    renderSearchDropdown();
                }
            })
            .catch(function() {
                hideSearchDropdown();
            });
    }, 1500);
}

function renderSearchDropdown() {
    if (!currentSearchResults || currentSearchResults.length === 0) {
        searchResults.innerHTML = '<div class="search-no-results">No players found</div>';
        searchResults.classList.add('visible');
        urlInput.setAttribute("aria-expanded", "true");
        return;
    }

    searchResults.innerHTML = '';
    currentSearchResults.forEach(function(player, index) {
        var div = document.createElement('div');
        div.className = 'search-result';
        div.setAttribute("role", "option");
        div.setAttribute("id", "searchResult_" + index);
        div.setAttribute("aria-selected", "false");
        div.dataset.fideId = player.fide_id;
        div.dataset.slug = player.slug;
        div.dataset.url = 'https://lichess.org/fide/' + player.fide_id + '/' + player.slug;

        var nameSpan = document.createElement('span');
        nameSpan.className = 'player-name';
        nameSpan.textContent = player.name;

        var fideSpan = document.createElement('span');
        fideSpan.className = 'player-fide';
        fideSpan.textContent = '(FIDE ' + player.fide_id + ')';

        div.appendChild(nameSpan);
        div.appendChild(fideSpan);

        div.addEventListener('mouseenter', function() {
            updateActiveSearchItem(index);
        });

        div.addEventListener('click', function() {
            selectSearchResult(div.dataset.url);
        });

        searchResults.appendChild(div);
    });

    searchResults.classList.add('visible');
    urlInput.setAttribute("aria-expanded", "true");
}

function hideSearchDropdown() {
    searchResults.classList.remove('visible');
    searchResults.innerHTML = '';
    activeSearchIndex = -1;
    currentSearchResults = [];
    urlInput.setAttribute("aria-expanded", "false");
    urlInput.setAttribute("aria-activedescendant", "");
}

function updateActiveSearchItem(index) {
    var items = searchResults.querySelectorAll('.search-result');
    items.forEach(function(item, i) {
        if (i === index) {
            item.classList.add('active');
            item.setAttribute("aria-selected", "true");
            urlInput.setAttribute("aria-activedescendant", item.id);
        } else {
            item.classList.remove('active');
            item.setAttribute("aria-selected", "false");
        }
    });
    activeSearchIndex = index;
}

function selectSearchResult(url) {
    urlInput.value = url;
    hideSearchDropdown();
}

function handleSearchKeydown(e) {
    var items = searchResults.querySelectorAll('.search-result');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (activeSearchIndex < items.length - 1) {
            updateActiveSearchItem(activeSearchIndex + 1);
            items[activeSearchIndex].scrollIntoView({ block: 'nearest' });
        }
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (activeSearchIndex > 0) {
            updateActiveSearchItem(activeSearchIndex - 1);
            items[activeSearchIndex].scrollIntoView({ block: 'nearest' });
        }
    } else if (e.key === 'Enter') {
        if (activeSearchIndex >= 0 && items[activeSearchIndex]) {
            e.preventDefault();
            selectSearchResult(items[activeSearchIndex].dataset.url);
        }
    } else if (e.key === 'Escape') {
        hideSearchDropdown();
    }
}

// Wire up input event for debounced search
urlInput.addEventListener('input', function() {
    debounceSearch(urlInput.value.trim());
});

// Wire up keydown for keyboard navigation
urlInput.addEventListener('keydown', handleSearchKeydown);

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!urlInput.contains(e.target) && !searchResults.contains(e.target)) {
        hideSearchDropdown();
    }
});
```

- [ ] **Step 2: Verify in browser**

Test the following:
1. Type 2+ chars, wait 1.5s, dropdown appears with results
2. Type a URL, dropdown does not appear
3. ArrowDown/ArrowUp navigates through results
4. Enter selects the active result
5. Escape closes the dropdown
6. Clicking outside closes the dropdown
7. Clicking a result fills the input with the full URL
8. Dropdown re-debounces on each keystroke (previous request abandoned)

- [ ] **Step 3: Commit**

```bash
git add static/app.js
git commit -m "feat: add search autocomplete with debounce and keyboard nav"
```

---

### Task 7: Run full test suite and verify integration

**Files:**
- Test: `tests/test_app.py` (all tests)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/test_app.py -v`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Manual integration test**

1. Start the dev server: `flask run --debug`
2. Open http://localhost:5000
3. Type 'carl' in the input field
4. Wait for dropdown to appear with matching players
5. Select a player with arrow keys + Enter
6. Verify the input is populated with the full FIDE URL
7. Click Fetch Games and verify it works as before
8. Verify cache is populated at `CACHE_DIR/search/`

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: F1 player search - autocomplete with backend /search endpoint"
```

---

## Self-Review

**1. Spec coverage:**
- [x] Backend /search endpoint with scraping, caching, rate limiting
- [x] Cache functions in cache.py (permanent cache)
- [x] SearchRateLimiter in rate_limit.py (1 per 5s per IP)
- [x] Frontend dropdown with debounce (1500ms)
- [x] Keyboard navigation (ArrowDown/Up, Enter, Escape)
- [x] ARIA attributes (listbox, option, aria-expanded, aria-activedescendant)
- [x] Tests for /search endpoint, caching, rate limiting

**2. Placeholder scan:** No TBDs, TODOs, or vague instructions found.

**3. Type consistency:**
- cache.py: `get_cached_search(query)` returns `Optional[list]`, `cache_search(query, results)` takes `list`
- rate_limit.py: `SearchRateLimiter.check(ip)` returns `Tuple[bool, float]`
- app.py: `/search?q=...` returns JSON array of `{fide_id, name, slug}`
- app.js: `currentSearchResults` array of `{fide_id, name, slug}` objects
- All function signatures and data shapes are consistent across tasks.
