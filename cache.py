"""Disk-based caching module for Lichess data with TTL support."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Configuration from environment variables
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))


def _get_hash(key: str) -> str:
    """Generate SHA256 hash of key, truncated to 16 hex chars."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _get_metadata_path(subdir: str, hash_key: str) -> Path:
    """Get path to metadata JSON file."""
    return Path(CACHE_DIR) / subdir / f"{hash_key}.meta"


def _get_pgn_path(subdir: str, hash_key: str) -> Path:
    """Get path to PGN cache file."""
    return Path(CACHE_DIR) / subdir / f"{hash_key}.pgn"


def _is_expired(metadata: dict) -> bool:
    """Check if cached entry has exceeded TTL."""
    cached_at = datetime.fromisoformat(metadata["cached_at"])
    ttl = timedelta(hours=CACHE_TTL_HOURS)
    return datetime.utcnow() - cached_at > ttl


def _cleanup_expired(subdir: str, hash_key: str) -> None:
    """Remove expired cache files."""
    pgn_path = _get_pgn_path(subdir, hash_key)
    meta_path = _get_metadata_path(subdir, hash_key)
    pgn_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)


def get_cached_tournament(tournament_id: str) -> Optional[str]:
    """Get cached raw PGN for a tournament.

    Args:
        tournament_id: The Lichess tournament ID

    Returns:
        Cached PGN text if found and not expired, None otherwise.
        Expired entries are automatically deleted.
    """
    hash_key = _get_hash(tournament_id)
    meta_path = _get_metadata_path("tournaments", hash_key)
    pgn_path = _get_pgn_path("tournaments", hash_key)

    if not meta_path.exists() or not pgn_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text())
        if _is_expired(metadata):
            _cleanup_expired("tournaments", hash_key)
            return None
        return pgn_path.read_text()
    except (json.JSONDecodeError, IOError):
        _cleanup_expired("tournaments", hash_key)
        return None


def cache_tournament(tournament_id: str, pgn_text: str, url: str = "") -> None:
    """Cache raw PGN data for a tournament.

    Args:
        tournament_id: The Lichess tournament ID
        pgn_text: Raw PGN data to cache
        url: Optional URL for metadata
    """
    hash_key = _get_hash(tournament_id)
    pgn_path = _get_pgn_path("tournaments", hash_key)
    meta_path = _get_metadata_path("tournaments", hash_key)

    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    pgn_path.write_text(pgn_text)

    metadata = {
        "cached_at": datetime.utcnow().isoformat(),
        "tournament_id": tournament_id,
        "url": url,
    }
    meta_path.write_text(json.dumps(metadata))


def get_cached_player(fide_id: str, tournament_id: str) -> Optional[str]:
    """Get cached filtered PGN for a player-tournament combination.

    Args:
        fide_id: The FIDE ID of the player
        tournament_id: The Lichess tournament ID

    Returns:
        Cached filtered PGN if found and not expired, None otherwise.
        Expired entries are automatically deleted.
    """
    key = f"{fide_id}_{tournament_id}"
    hash_key = _get_hash(key)
    meta_path = _get_metadata_path("players", hash_key)
    pgn_path = _get_pgn_path("players", hash_key)

    if not meta_path.exists() or not pgn_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text())
        if _is_expired(metadata):
            _cleanup_expired("players", hash_key)
            return None
        return pgn_path.read_text()
    except (json.JSONDecodeError, IOError):
        _cleanup_expired("players", hash_key)
        return None


def cache_player(fide_id: str, tournament_id: str, pgn_text: str) -> None:
    """Cache filtered PGN for a player-tournament combination.

    Args:
        fide_id: The FIDE ID of the player
        tournament_id: The Lichess tournament ID
        pgn_text: Filtered PGN data to cache
    """
    key = f"{fide_id}_{tournament_id}"
    hash_key = _get_hash(key)
    pgn_path = _get_pgn_path("players", hash_key)
    meta_path = _get_metadata_path("players", hash_key)

    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    pgn_path.write_text(pgn_text)

    metadata = {
        "cached_at": datetime.utcnow().isoformat(),
        "fide_id": fide_id,
        "tournament_id": tournament_id,
    }
    meta_path.write_text(json.dumps(metadata))
