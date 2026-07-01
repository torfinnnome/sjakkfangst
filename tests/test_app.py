"""Tests for the Flask HTTP layer (app.py)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import app as app_module
import cache
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
                          return_value={"stats": [], "player_name": "Carlsen, Magnus"}):
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
