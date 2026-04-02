"""Tests for cache module."""

import json
import os
import tempfile
from datetime import datetime, timedelta
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
    old_time = (datetime.utcnow() - timedelta(hours=25)).isoformat()
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
    old_time = (datetime.utcnow() - timedelta(hours=25)).isoformat()
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
