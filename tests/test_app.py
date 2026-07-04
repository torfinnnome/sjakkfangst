"""Tests for the Flask HTTP layer (app.py)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest
import requests as requests_lib

import app as app_module
import cache
import rate_limit
from rate_limit import RateLimiter, MAX_REQUESTS_PER_IP


@pytest.fixture
def temp_cache_dir():
    """Redirect the disk cache to a temp dir so tests don't touch the host cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original = cache.CACHE_DIR
        cache.CACHE_DIR = tmpdir
        yield tmpdir
        cache.CACHE_DIR = original


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def fresh_limiter(monkeypatch):
    """Replace the module-level rate limiter singleton with a fresh one."""
    limiter = RateLimiter()
    monkeypatch.setattr(app_module, "rate_limiter", limiter)
    return limiter


VALID_URL = "https://lichess.org/fide/1503014/Carlsen_Magnus"
SAME_ORIGIN = {"Origin": "http://localhost"}


def parse_sse_events(response):
    """Parse a text/event-stream response into a list of decoded JSON payloads."""
    events = []
    for chunk in response.data.decode("utf-8").split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[len("data: "):]))
    return events


class TestIndex:
    def test_index_returns_form(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b'id="fetch-form"' in r.data
        # The example URL should be present (not escaped into oblivion)
        assert b"lichess.org/fide/1503014" in r.data


class TestFetchStreamValidation:
    def test_missing_url_returns_400(self, client, fresh_limiter):
        r = client.get("/fetch_stream", headers=SAME_ORIGIN)
        assert r.status_code == 400

    def test_empty_url_returns_400(self, client, fresh_limiter):
        r = client.get("/fetch_stream?url=", headers=SAME_ORIGIN)
        assert r.status_code == 400

    def test_invalid_url_returns_400(self, client, fresh_limiter):
        r = client.get("/fetch_stream?url=https://example.com/nope", headers=SAME_ORIGIN)
        assert r.status_code == 400

    def test_cross_origin_blocked(self, client, fresh_limiter):
        r = client.get(f"/fetch_stream?url={VALID_URL}", headers={"Origin": "https://evil.com"})
        assert r.status_code == 403


class TestRateLimiting:
    def test_rate_limit_event_when_per_ip_exceeded(self, client, fresh_limiter):
        # Exhaust the per-IP allowance
        for _ in range(MAX_REQUESTS_PER_IP):
            client.get(f"/fetch_stream?url={VALID_URL}", headers=SAME_ORIGIN)

        r = client.get(f"/fetch_stream?url={VALID_URL}", headers=SAME_ORIGIN)
        # Rate-limited responses are SSE so the client can show a countdown
        assert r.status_code == 200
        assert r.mimetype == "text/event-stream"
        events = parse_sse_events(r)
        assert events, "expected a rate_limit event"
        assert "rate_limit" in events[0]
        assert "wait" in events[0]
        assert events[0]["wait"] >= 0


class TestFetchStreamHappyPath:
    """End-to-end SSE flow with everything mocked except the cache layer."""

    def test_streams_tournaments_progress_and_done(self, client, temp_cache_dir, fresh_limiter):
        broadcasts = [
            {"url": "https://lichess.org/broadcast/slug-a/round-a/idA", "name": "Tournament A"},
            {"url": "https://lichess.org/broadcast/slug-b/round-b/idB", "name": "Tournament B"},
        ]

        # First tournament: player cache hit. Second: cache miss, then download.
        cached_player_pgn = '[Event "A"]\n1. e4 e5'
        downloaded_pgn = '[Event "B"]\n1. d4 d5'
        filtered_pgn = '[Event "B"]\n1. d4 d5'

        with patch.object(app_module, "get_broadcasts", return_value=broadcasts), \
             patch.object(app_module, "get_cached_player",
                          side_effect=lambda f, t: cached_player_pgn if t == "idA" else None), \
             patch.object(app_module, "get_cached_tournament", return_value=None), \
             patch.object(app_module, "download_broadcast_pgn", return_value=downloaded_pgn), \
             patch.object(app_module, "filter_games_by_fide", return_value=filtered_pgn), \
              patch.object(app_module, "collect_opening_stats",
                           return_value={"stats": [], "player_name": "Carlsen, Magnus"}), \
              patch.object(app_module, "collect_opponent_stats",
                           return_value={"stats": [], "player_name": ""}):
            # Consume the streaming response while patches are active; the SSE
            # generator is lazily evaluated when data is accessed.
            r = client.get(f"/fetch_stream?url={VALID_URL}", headers=SAME_ORIGIN)
            events = parse_sse_events(r)
            task_id = events[-1]["id"]
            dl = client.get(f"/download/{task_id}")

        assert r.status_code == 200
        assert r.mimetype == "text/event-stream"

        # Expected sequence: tournaments list, two progress events, done
        assert "tournaments" in events[0]
        assert len(events[0]["tournaments"]) == 2
        assert events[0]["player_hash"] == "#players/1503014"

        # First progress event = player cache hit
        progress_events = [e for e in events if "index" in e]
        assert len(progress_events) == 2
        assert progress_events[0]["index"] == 0
        assert progress_events[0]["cached"] is True

        # Final done event carries task id + stats
        done = events[-1]
        assert done["done"] is True
        assert done["progress"] == 100
        assert "id" in done
        assert done["player_name"] == "Carlsen, Magnus"

        # The task id should be retrievable via /download/<id>
        assert dl.status_code == 200
        assert dl.mimetype == "application/x-chess-pgn"
        assert b"1. e4 e5" in dl.data

    def test_no_broadcasts_yields_error(self, client, temp_cache_dir, fresh_limiter):
        with patch.object(app_module, "get_broadcasts", return_value=[]):
            r = client.get(f"/fetch_stream?url={VALID_URL}", headers=SAME_ORIGIN)
            events = parse_sse_events(r)
        assert events and events[0]["error"] == "No broadcasts found"

    def test_no_matching_games_yields_error(self, client, temp_cache_dir, fresh_limiter):
        broadcasts = [{"url": "https://lichess.org/broadcast/slug/x/idX", "name": "X"}]
        with patch.object(app_module, "get_broadcasts", return_value=broadcasts), \
             patch.object(app_module, "get_cached_player", return_value=None), \
             patch.object(app_module, "get_cached_tournament", return_value=None), \
             patch.object(app_module, "download_broadcast_pgn", return_value=""), \
             patch.object(app_module, "filter_games_by_fide", return_value=""):
            r = client.get(f"/fetch_stream?url={VALID_URL}", headers=SAME_ORIGIN)
            events = parse_sse_events(r)
        assert any(e.get("error") == "No matching games found" for e in events)


class TestDownload:
    def test_unknown_task_returns_404(self, client, temp_cache_dir):
        r = client.get("/download/does-not-exist")
        assert r.status_code == 404

    def test_expired_task_returns_404(self, client, temp_cache_dir, monkeypatch):
        # Write a task, then backdate its metadata past the TTL
        cache.cache_task("oldtask", "1. e4", "old.pgn")
        from datetime import datetime, timedelta, timezone
        hash_key = cache._get_hash("oldtask")
        meta_path = Path(temp_cache_dir) / "tasks" / f"{hash_key}.meta"
        metadata = json.loads(meta_path.read_text())
        metadata["cached_at"] = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        meta_path.write_text(json.dumps(metadata))

        assert client.get("/download/oldtask").status_code == 404

    def test_round_trip_through_disk_cache(self, client, temp_cache_dir):
        # cache_task writes to disk; /download reads via get_cached_task
        cache.cache_task("roundtrip", "1. e4 e5", "games.pgn")
        r = client.get("/download/roundtrip")
        assert r.status_code == 200
        assert b"1. e4 e5" in r.data


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

    def test_cache_ignores_ttl(self, temp_cache_dir, monkeypatch):
        """Search cache has no TTL; setting CACHE_TTL_HOURS to 0 doesn't evict it."""
        results = [{"fide_id": "1503014", "name": "Carlsen, Magnus", "slug": "MagnusCarlsen"}]
        cache.cache_search("carlsen", results)
        monkeypatch.setattr(cache, "CACHE_TTL_HOURS", 0)
        cached = cache.get_cached_search("carlsen")
        assert cached is not None
        assert len(cached) == 1

    def test_cached_empty_list_treated_as_miss(self, temp_cache_dir):
        """A cached [] is treated as a miss so stale empties self-heal.

        Reproduces the møklebust-lien incident: a [] cached before the
        ASCII-fold fix would block the fix forever. get_cached_search must
        return None for [] so the route re-runs search_fide_players.
        """
        cache.cache_search("møklebust-lien", [])
        assert cache.get_cached_search("møklebust-lien") is None
        # The stale file should be removed so it can't accumulate.
        from pathlib import Path
        import hashlib
        h = hashlib.md5("møklebust-lien".encode()).hexdigest()[:16]
        assert not (Path(temp_cache_dir) / "search" / f"{h}.json").exists()

    def test_empty_results_not_cached_by_route(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        """The /search route must not cache empty results, so a future fix
        (or a newly-registered player) isn't blocked by a stale [] entry."""
        monkeypatch.setattr(app_module, "_search_limiter", rate_limit.SearchRateLimiter())
        with patch("app.fetch_with_retry", return_value=_resp('<div class="fide-players-table"></div>')):
            r = client.get("/search?q=zzznomatch")
        assert r.status_code == 200
        assert r.get_json() == []
        # Empty result must not be written to the search cache.
        assert cache.get_cached_search("zzznomatch") is None


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
        import rate_limit
        from rate_limit import SearchRateLimiter
        from unittest.mock import MagicMock
        import time
        limiter = SearchRateLimiter()
        limiter.check("127.0.0.1")
        base_time = time.time()
        mock_time = MagicMock()
        mock_time.time = MagicMock(return_value=base_time + 6)
        monkeypatch.setattr(rate_limit, "time", mock_time)
        allowed, _ = limiter.check("127.0.0.1")
        assert allowed is True

    def test_different_ips_are_independent(self):
        from rate_limit import SearchRateLimiter
        limiter = SearchRateLimiter()
        limiter.check("127.0.0.1")
        allowed, _ = limiter.check("192.168.1.1")
        assert allowed is True


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
        <div class="fide-players-table">
          <a href="/fide/1503014/MagnusCarlsen" class="player-intro__name">Carlsen, Magnus</a>
          <a href="/fide/1001234/HikaruNakamura" class="player-intro__name">Nakamura, Hikaru</a>
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

        mock_html = '<div class="fide-players-table"><a href="/fide/1/x" class="player-intro__name">A</a></div>'
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


def _resp(html: str) -> requests_lib.Response:
    """Build a fake requests.Response carrying the given HTML body."""
    r = requests_lib.Response()
    r._content = html.encode()
    r.status_code = 200
    return r


def _player_html(fide_id: str, slug: str, name: str) -> str:
    return (
        f'<div class="fide-players-table">'
        f'<a href="/fide/{fide_id}/{slug}" class="player-intro__name">{name}</a>'
        f'</div>'
    )


def _dispatch_by_query(responses):
    """side_effect for fetch_with_retry that picks a response by the `q=` param.

    `responses` maps the decoded query (e.g. "Bø") to a Response or an Exception.
    """
    def _side_effect(url, timeout=15):
        q = unquote(url.split("q=", 1)[1])
        outcome = responses[q]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return _side_effect


class TestAsciiFold:
    def test_pure_ascii_unchanged(self):
        assert app_module.ascii_fold("Carlsen") == "Carlsen"
        assert app_module.ascii_fold("1503014") == "1503014"
        assert app_module.ascii_fold("") == ""

    def test_manual_folds(self):
        assert app_module.ascii_fold("Bø") == "Bo"
        assert app_module.ascii_fold("Børre") == "Borre"
        assert app_module.ascii_fold("Ærlig") == "Arlig"
        assert app_module.ascii_fold("Straße") == "Strasse"
        assert app_module.ascii_fold("Øster") == "Oster"
        assert app_module.ascii_fold("cœur") == "coeur"

    def test_nfkd_accents(self):
        assert app_module.ascii_fold("José") == "Jose"
        assert app_module.ascii_fold("Müller") == "Muller"
        assert app_module.ascii_fold("Öster") == "Oster"
        assert app_module.ascii_fold("Ñoño") == "Nono"
        assert app_module.ascii_fold("Renée") == "Renee"
        assert app_module.ascii_fold("Søraå") == "Soraa"  # ø manual + å via NFKD

    def test_case_preserved(self):
        assert app_module.ascii_fold("Ø") == "O"
        assert app_module.ascii_fold("ø") == "o"
        assert app_module.ascii_fold("Æ") == "A"
        assert app_module.ascii_fold("ẞ") == "SS"


class TestSearchVariants:
    """search_fide_players searches ASCII-folded variants for non-ASCII queries."""

    def _setup(self, monkeypatch):
        monkeypatch.setattr(app_module, "_search_limiter", rate_limit.SearchRateLimiter())

    def test_ascii_query_single_fetch(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        self._setup(monkeypatch)
        calls = []

        def _side_effect(url, timeout=15):
            calls.append(url)
            return _resp(_player_html("1503014", "MagnusCarlsen", "Carlsen, Magnus"))

        with patch("app.fetch_with_retry", side_effect=_side_effect):
            r = client.get("/search?q=carl")

        assert r.status_code == 200
        assert len(calls) == 1, "pure-ASCII query should trigger exactly one fetch"
        assert len(r.get_json()) == 1

    def test_non_ascii_fetches_both_variants_and_merges(
        self, client, temp_cache_dir, fresh_limiter, monkeypatch
    ):
        self._setup(monkeypatch)
        responses = {
            "Bø": _resp(_player_html("111", "BorreLars", "Børre, Lars")),
            "Bo": _resp(_player_html("222", "BorreSven", "Borre, Sven")),
        }
        with patch("app.fetch_with_retry", side_effect=_dispatch_by_query(responses)):
            r = client.get("/search?q=Bø")

        data = r.get_json()
        assert r.status_code == 200
        fide_ids = sorted(p["fide_id"] for p in data)
        assert fide_ids == ["111", "222"], "results from both variants should be merged"

    def test_folded_only_results_are_kept(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        """The motivating bug: folded-variant results must survive the name filter.

        Searching "Bø" returns a player via the "Bo" fetch whose name has no "ø"
        (e.g. "Borre, Sven"). The old single-query filter would drop it; the new
        any-variant filter must keep it.
        """
        self._setup(monkeypatch)
        responses = {
            "Bø": _resp('<div class="fide-players-table"></div>'),  # no matches
            "Bo": _resp(_player_html("222", "BorreSven", "Borre, Sven")),
        }
        with patch("app.fetch_with_retry", side_effect=_dispatch_by_query(responses)):
            r = client.get("/search?q=Bø")

        data = r.get_json()
        assert r.status_code == 200
        assert len(data) == 1
        assert data[0]["fide_id"] == "222"

    def test_dedupes_across_variants(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        self._setup(monkeypatch)
        same_player = _player_html("111", "BorreLars", "Børre, Lars")
        responses = {"Bø": _resp(same_player), "Bo": _resp(same_player)}
        with patch("app.fetch_with_retry", side_effect=_dispatch_by_query(responses)):
            r = client.get("/search?q=Bø")

        data = r.get_json()
        assert r.status_code == 200
        assert len(data) == 1, "same FIDE ID from both variants must be deduped"
        assert data[0]["fide_id"] == "111"

    def test_partial_failure_returns_successful_results(
        self, client, temp_cache_dir, fresh_limiter, monkeypatch
    ):
        """If one variant fetch fails, the other's results are still returned (no 500)."""
        self._setup(monkeypatch)
        responses = {
            "Bø": _resp(_player_html("111", "BorreLars", "Børre, Lars")),
            "Bo": requests_lib.RequestException("folded fetch failed"),
        }
        with patch("app.fetch_with_retry", side_effect=_dispatch_by_query(responses)):
            r = client.get("/search?q=Bø")

        data = r.get_json()
        assert r.status_code == 200
        assert len(data) == 1
        assert data[0]["fide_id"] == "111"

    def test_all_variants_fail_returns_500(self, client, temp_cache_dir, fresh_limiter, monkeypatch):
        self._setup(monkeypatch)
        responses = {
            "Bø": requests_lib.RequestException("fail-1"),
            "Bo": requests_lib.RequestException("fail-2"),
        }
        with patch("app.fetch_with_retry", side_effect=_dispatch_by_query(responses)):
            r = client.get("/search?q=Bø")

        assert r.status_code == 500
