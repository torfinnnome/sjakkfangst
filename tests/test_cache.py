"""Tests for cache module."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

import cache


@pytest.fixture
def temp_cache_dir():
    """Create a temporary cache directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_cache_dir = cache.CACHE_DIR
        cache.CACHE_DIR = tmpdir
        yield tmpdir
        cache.CACHE_DIR = original_cache_dir


def test_get_hash():
    """Test that _get_hash generates consistent hashes."""
    hash1 = cache._get_hash("test_key")
    hash2 = cache._get_hash("test_key")
    hash3 = cache._get_hash("different_key")

    assert hash1 == hash2, "Same key should produce same hash"
    assert hash1 != hash3, "Different keys should produce different hashes"
    assert len(hash1) == 16, "Hash should be truncated to 16 characters"


def test_cache_tournament_and_get(temp_cache_dir):
    """Test caching and retrieving tournament data."""
    tournament_id = "test-tournament-123"
    pgn_data = '[Event "Test"]\n1. e4 e5'
    url = "https://example.com/test"

    # Cache the data
    cache.cache_tournament(tournament_id, pgn_data, url)

    # Verify files were created
    hash_key = cache._get_hash(tournament_id)
    pgn_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.pgn"
    meta_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.meta"

    assert pgn_path.exists(), "PGN file should be created"
    assert meta_path.exists(), "Metadata file should be created"
    assert pgn_path.read_text() == pgn_data, "PGN content should match"

    # Verify metadata
    metadata = json.loads(meta_path.read_text())
    assert metadata["tournament_id"] == tournament_id
    assert metadata["url"] == url
    assert "cached_at" in metadata

    # Retrieve from cache
    cached = cache.get_cached_tournament(tournament_id)
    assert cached == pgn_data, "Retrieved data should match cached data"


def test_get_cached_tournament_not_found(temp_cache_dir):
    """Test retrieval of non-existent tournament cache."""
    result = cache.get_cached_tournament("non-existent-id")
    assert result is None


def test_cache_player_and_get(temp_cache_dir):
    """Test caching and retrieving player data."""
    fide_id = "1234567"
    tournament_id = "test-tournament-456"
    pgn_data = '[Event "Test"]\n[White "Player1"]\n1. d4 d5'

    # Cache the data
    cache.cache_player(fide_id, tournament_id, pgn_data)

    # Verify files were created
    key = f"{fide_id}_{tournament_id}"
    hash_key = cache._get_hash(key)
    pgn_path = Path(temp_cache_dir) / "players" / f"{hash_key}.pgn"
    meta_path = Path(temp_cache_dir) / "players" / f"{hash_key}.meta"

    assert pgn_path.exists()
    assert meta_path.exists()

    # Retrieve from cache
    cached = cache.get_cached_player(fide_id, tournament_id)
    assert cached == pgn_data


def test_tournament_expiration(temp_cache_dir):
    """Test that expired tournament cache entries are removed."""
    tournament_id = "expired-tournament"
    pgn_data = '[Event "Test"]\n1. e4 e5'

    # Cache with old timestamp
    cache.cache_tournament(tournament_id, pgn_data)

    # Manually modify metadata to be expired
    hash_key = cache._get_hash(tournament_id)
    meta_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.meta"
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    metadata = json.loads(meta_path.read_text())
    metadata["cached_at"] = old_time
    meta_path.write_text(json.dumps(metadata))

    # Should return None and delete expired files
    result = cache.get_cached_tournament(tournament_id)
    assert result is None, "Expired cache should return None"
    assert not meta_path.exists(), "Expired metadata should be deleted"


def test_player_expiration(temp_cache_dir):
    """Test that expired player cache entries are removed."""
    fide_id = "7654321"
    tournament_id = "expired-tourney"
    pgn_data = '[Event "Test"]\n1. c4 c5'

    cache.cache_player(fide_id, tournament_id, pgn_data)

    # Manually modify metadata to be expired
    key = f"{fide_id}_{tournament_id}"
    hash_key = cache._get_hash(key)
    meta_path = Path(temp_cache_dir) / "players" / f"{hash_key}.meta"
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    metadata = json.loads(meta_path.read_text())
    metadata["cached_at"] = old_time
    meta_path.write_text(json.dumps(metadata))

    result = cache.get_cached_player(fide_id, tournament_id)
    assert result is None
    assert not meta_path.exists()


def test_corrupted_metadata_handling(temp_cache_dir):
    """Test handling of corrupted metadata files."""
    tournament_id = "corrupted-tourney"

    # Create files manually
    hash_key = cache._get_hash(tournament_id)
    pgn_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.pgn"
    meta_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.meta"

    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    pgn_path.write_text('[Event "Test"]')
    meta_path.write_text("invalid json {[")

    # Should handle gracefully and return None
    result = cache.get_cached_tournament(tournament_id)
    assert result is None
    # Should clean up corrupted files
    assert not pgn_path.exists()
    assert not meta_path.exists()


def test_parse_tournament_end_date():
    """Test parsing of latest game date from PGN."""
    pgn_old = """[Event "Old Tournament"]
[Date "2024.01.15"]
1. e4 e5

[Event "Old Tournament"]
[Date "2024.01.16"]
1. d4 d5"""

    pgn_recent = """[Event "Recent Tournament"]
[Date "2024.12.25"]
1. e4 e5

[Event "Recent Tournament"]
[Date "2024.12.26"]
1. d4 d5"""

    pgn_no_date = """[Event "Unknown Date"]
1. e4 e5"""

    result_old = cache._parse_tournament_end_date(pgn_old)
    assert result_old == datetime(2024, 1, 16, tzinfo=timezone.utc)

    result_recent = cache._parse_tournament_end_date(pgn_recent)
    assert result_recent == datetime(2024, 12, 26, tzinfo=timezone.utc)

    result_no_date = cache._parse_tournament_end_date(pgn_no_date)
    assert result_no_date is None


def test_parse_tournament_end_date_dash_format():
    """Test parsing of dash-formatted dates (YYYY-MM-DD) from Lichess broadcasts."""
    pgn_dash = """[Event "Dash Format"]
[Date "2024-01-15"]
1. e4 e5

[Event "Dash Format"]
[Date "2024-01-16"]
1. d4 d5"""

    result = cache._parse_tournament_end_date(pgn_dash)
    assert result == datetime(2024, 1, 16, tzinfo=timezone.utc)


def test_determine_tournament_status_completed():
    """Test status detection for completed tournament (> 5 days)."""
    # Create PGN with date 10 days ago
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y.%m.%d")
    pgn = f'''[Event "Old Tournament"]
[Date "{old_date}"]
1. e4 e5'''

    status, end_date = cache._determine_tournament_status(pgn)
    assert status == "completed"
    assert end_date is not None


def test_determine_tournament_status_ongoing():
    """Test status detection for ongoing/recent tournament (< 5 days)."""
    # Create PGN with date 2 days ago
    recent_date = (datetime.now() - timedelta(days=2)).strftime("%Y.%m.%d")
    pgn = f'''[Event "Recent Tournament"]
[Date "{recent_date}"]
1. e4 e5'''

    status, end_date = cache._determine_tournament_status(pgn)
    assert status == "ongoing"
    assert end_date is not None


def test_completed_tournament_never_expires(temp_cache_dir):
    """Test that completed tournaments are cached indefinitely."""
    tournament_id = "completed-tournament"
    old_date = (datetime.now() - timedelta(days=30)).strftime("%Y.%m.%d")
    pgn_data = f'''[Event "Old Tournament"]
[Date "{old_date}"]
1. e4 e5'''

    # Cache the tournament
    cache.cache_tournament(tournament_id, pgn_data)

    # Manually set cached_at to 30 days ago (should not matter for completed tournaments)
    hash_key = cache._get_hash(tournament_id)
    meta_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.meta"
    metadata = json.loads(meta_path.read_text())
    assert metadata["status"] == "completed"

    # Modify cached_at to be very old
    metadata["cached_at"] = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    meta_path.write_text(json.dumps(metadata))

    # Should still return cached data for completed tournaments
    result = cache.get_cached_tournament(tournament_id)
    assert result == pgn_data, "Completed tournaments should never expire"


def test_ongoing_tournament_expires(temp_cache_dir):
    """Test that ongoing tournaments expire after TTL."""
    tournament_id = "ongoing-tournament"
    recent_date = (datetime.now() - timedelta(days=2)).strftime("%Y.%m.%d")
    pgn_data = f'''[Event "Recent Tournament"]
[Date "{recent_date}"]
1. e4 e5'''

    # Cache the tournament
    cache.cache_tournament(tournament_id, pgn_data)

    # Verify it's marked as ongoing
    hash_key = cache._get_hash(tournament_id)
    meta_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.meta"
    metadata = json.loads(meta_path.read_text())
    assert metadata["status"] == "ongoing"

    # Modify cached_at to be expired
    metadata["cached_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    meta_path.write_text(json.dumps(metadata))

    # Should return None for expired ongoing tournaments
    result = cache.get_cached_tournament(tournament_id)
    assert result is None, "Ongoing tournaments should expire after TTL"


def test_ongoing_to_completed_transition_on_read(temp_cache_dir):
    """Test that a tournament cached as 'ongoing' gets updated to 'completed' on read.

    This is the key fix: when a tournament was cached while ongoing, and the PGN's
    last game date has since crossed the 5-day threshold, the next read should
    re-evaluate the status and update metadata to 'completed' (infinite TTL).
    """
    tournament_id = "transition-tournament"
    # PGN has a date >5 days ago → will be detected as completed
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y.%m.%d")
    pgn_data = f'''[Event "Finished Tournament"]
[Date "{old_date}"]
1. e4 e5'''

    # Manually create cache with "ongoing" status (simulating stale metadata)
    hash_key = cache._get_hash(tournament_id)
    pgn_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.pgn"
    meta_path = Path(temp_cache_dir) / "tournaments" / f"{hash_key}.meta"

    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    pgn_path.write_text(pgn_data)

    # Write metadata as "ongoing" with old cached_at (would normally expire)
    metadata = {
        "cached_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        "tournament_id": tournament_id,
        "url": "",
        "status": "ongoing",
    }
    meta_path.write_text(json.dumps(metadata))

    # Read should re-evaluate status from PGN, update to "completed", and NOT expire
    result = cache.get_cached_tournament(tournament_id)
    assert result == pgn_data, "Completed tournament should not expire"

    # Verify metadata was updated
    updated_metadata = json.loads(meta_path.read_text())
    assert updated_metadata["status"] == "completed", "Status should be updated to completed"


def test_completed_player_cache_never_expires(temp_cache_dir):
    """Test that a player cache entry for a completed tournament never expires."""
    fide_id = "1503014"
    tournament_id = "finished-tournament"
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y.%m.%d")
    pgn_data = f'''[Event "Finished"]
[Date "{old_date}"]
[White "A"][Black "B"][Result "1-0"]
[WhiteFideId "1503014"]

1. e4 e5 1-0'''

    cache.cache_player(fide_id, tournament_id, pgn_data)

    hash_key = cache._get_hash(f"{fide_id}_{tournament_id}")
    meta_path = Path(temp_cache_dir) / "players" / f"{hash_key}.meta"
    metadata = json.loads(meta_path.read_text())

    assert metadata["status"] == "completed"

    # Modify cached_at to be very old — should still return cached data
    metadata["cached_at"] = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    meta_path.write_text(json.dumps(metadata))

    result = cache.get_cached_player(fide_id, tournament_id)
    assert result == pgn_data, "Completed player cache should never expire"


def test_missing_status_recovered_on_read(temp_cache_dir):
    """Test that a player cache entry without a status field has it auto-detected on read.

    Old cache entries may lack the 'status' field. On read, the status should be
    detected from the PGN and written back to metadata.
    """
    fide_id = "1503014"
    tournament_id = "missing-status-tourney"
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y.%m.%d")
    pgn_data = f'''[Event "Finished"]
[Date "{old_date}"]
1. e4 e5'''

    # Manually create cache entry without status field
    hash_key = cache._get_hash(f"{fide_id}_{tournament_id}")
    pgn_path = Path(temp_cache_dir) / "players" / f"{hash_key}.pgn"
    meta_path = Path(temp_cache_dir) / "players" / f"{hash_key}.meta"

    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    pgn_path.write_text(pgn_data)

    # Write metadata WITHOUT status field (old format)
    metadata = {
        "cached_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        "fide_id": fide_id,
        "tournament_id": tournament_id,
    }
    meta_path.write_text(json.dumps(metadata))

    # Read should auto-detect status from PGN and NOT expire
    result = cache.get_cached_player(fide_id, tournament_id)
    assert result == pgn_data, "Entry with missing status should be recovered"

    # Verify metadata was updated with status
    updated_metadata = json.loads(meta_path.read_text())
    assert updated_metadata["status"] == "completed"


def test_ongoing_player_cache_expires(temp_cache_dir):
    """Test that a player cache entry for an ongoing tournament expires after TTL."""
    fide_id = "1503014"
    tournament_id = "ongoing-tournament"
    recent_date = datetime.now().strftime("%Y.%m.%d")
    pgn_data = f'''[Event "Ongoing"]
[Date "{recent_date}"]
[White "A"][Black "B"][Result "1-0"]
[WhiteFideId "1503014"]

1. e4 e5 1-0'''

    cache.cache_player(fide_id, tournament_id, pgn_data)

    hash_key = cache._get_hash(f"{fide_id}_{tournament_id}")
    meta_path = Path(temp_cache_dir) / "players" / f"{hash_key}.meta"
    metadata = json.loads(meta_path.read_text())

    assert metadata["status"] == "ongoing"

    # Should be readable immediately
    assert cache.get_cached_player(fide_id, tournament_id) == pgn_data

    # Modify cached_at to be expired
    metadata["cached_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    meta_path.write_text(json.dumps(metadata))

    result = cache.get_cached_player(fide_id, tournament_id)
    assert result is None, "Ongoing player cache should expire after TTL"
