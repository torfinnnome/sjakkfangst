"""Disk-based caching module for Lichess data with TTL support."""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Optional, Tuple

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment variables
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))
CACHE_COMPLETED_DAYS = int(os.environ.get("CACHE_COMPLETED_DAYS", "5"))


def _get_hash(key: str) -> str:
    """Generate SHA256 hash of key, truncated to 16 hex chars."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _get_metadata_path(subdir: str, hash_key: str) -> Path:
    """Get path to metadata JSON file."""
    return Path(CACHE_DIR) / subdir / f"{hash_key}.meta"


def _get_pgn_path(subdir: str, hash_key: str) -> Path:
    """Get path to PGN cache file."""
    return Path(CACHE_DIR) / subdir / f"{hash_key}.pgn"


def _parse_tournament_end_date(pgn_text: str) -> Optional[datetime]:
    """Extract the latest game date from PGN text.

    Args:
        pgn_text: Raw PGN data

    Returns:
        Latest date found in PGN headers, or None if not found.
    """
    # Look for Date headers in format [Date "YYYY.MM.DD"]
    date_pattern = r'\[Date "(\d{4})\.(\d{2})\.(\d{2})"\]'
    dates = []

    for match in re.finditer(date_pattern, pgn_text):
        try:
            year, month, day = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            dates.append(datetime(year, month, day, tzinfo=UTC))
        except ValueError:
            continue

    return max(dates) if dates else None


def _determine_tournament_status(pgn_text: str) -> Tuple[str, Optional[str]]:
    """Determine if tournament is completed or ongoing based on game dates.

    Args:
        pgn_text: Raw PGN data

    Returns:
        Tuple of (status, end_date_iso). Status is "completed" or "ongoing".
    """
    end_date = _parse_tournament_end_date(pgn_text)

    if end_date is None:
        # No date info - treat as ongoing (safer default)
        return "ongoing", None

    days_since_end = (datetime.now(UTC) - end_date).days

    if days_since_end > CACHE_COMPLETED_DAYS:
        return "completed", end_date.isoformat()
    else:
        return "ongoing", end_date.isoformat()


def _is_expired(metadata: dict) -> bool:
    """Check if cached entry has exceeded TTL.

    Completed tournaments never expire. Ongoing tournaments expire after TTL.
    """
    status = metadata.get("status", "ongoing")

    # Completed tournaments are cached indefinitely
    if status == "completed":
        return False

    # Ongoing tournaments use TTL
    cached_at = datetime.fromisoformat(metadata["cached_at"])
    # Ensure cached_at is timezone-aware if it wasn't already
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=UTC)
        
    ttl = timedelta(hours=CACHE_TTL_HOURS)
    return datetime.now(UTC) - cached_at > ttl


def _cleanup_expired(subdir: str, hash_key: str) -> None:
    """Remove expired cache files."""
    pgn_path = _get_pgn_path(subdir, hash_key)
    meta_path = _get_metadata_path(subdir, hash_key)
    pgn_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)


def get_cached_tournament(tournament_id: str) -> Optional[str]:
    """Get cached raw PGN for a tournament.

    Re-evaluates tournament status on each read so that ongoing tournaments
    that have since finished are updated to "completed" (infinite TTL).

    Args:
        tournament_id: The Lichess tournament ID

    Returns:
        Cached PGN text if found and not expired, None otherwise.
        Expired entries are automatically deleted.
        Completed tournaments never expire.
    """
    hash_key = _get_hash(tournament_id)
    meta_path = _get_metadata_path("tournaments", hash_key)
    pgn_path = _get_pgn_path("tournaments", hash_key)

    if not meta_path.exists() or not pgn_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text())
        pgn_text = pgn_path.read_text()

        # Re-evaluate status from the PGN to catch transitions
        current_status, _ = _determine_tournament_status(pgn_text)
        if metadata.get("status") != current_status:
            metadata["status"] = current_status
            meta_path.write_text(json.dumps(metadata))

        if _is_expired(metadata):
            _cleanup_expired("tournaments", hash_key)
            return None
        return pgn_text
    except (json.JSONDecodeError, IOError):
        _cleanup_expired("tournaments", hash_key)
        return None


def cache_tournament(tournament_id: str, pgn_text: str, url: str = "") -> None:
    """Cache raw PGN data for a tournament with automatic status detection.

    Args:
        tournament_id: The Lichess tournament ID
        pgn_text: Raw PGN data to cache
        url: Optional URL for metadata
    """
    try:
        hash_key = _get_hash(tournament_id)
        pgn_path = _get_pgn_path("tournaments", hash_key)
        meta_path = _get_metadata_path("tournaments", hash_key)

        pgn_path.parent.mkdir(parents=True, exist_ok=True)
        pgn_path.write_text(pgn_text)

        # Determine status based on game dates
        status, end_date = _determine_tournament_status(pgn_text)

        metadata = {
            "cached_at": datetime.now(UTC).isoformat(),
            "tournament_id": tournament_id,
            "url": url,
            "status": status,
        }
        if end_date:
            metadata["last_game_date"] = end_date

        meta_path.write_text(json.dumps(metadata))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write to cache: {e}")


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
    try:
        key = f"{fide_id}_{tournament_id}"
        hash_key = _get_hash(key)
        pgn_path = _get_pgn_path("players", hash_key)
        meta_path = _get_metadata_path("players", hash_key)

        pgn_path.parent.mkdir(parents=True, exist_ok=True)
        pgn_path.write_text(pgn_text)

        metadata = {
            "cached_at": datetime.now(UTC).isoformat(),
            "fide_id": fide_id,
            "tournament_id": tournament_id,
        }
        meta_path.write_text(json.dumps(metadata))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write to cache: {e}")
