"""Disk-based caching module for Lichess data with TTL support."""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment variables
CACHE_DIR = os.environ.get("CACHE_DIR", "/cache")
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "1"))
CACHE_COMPLETED_DAYS = int(os.environ.get("CACHE_COMPLETED_DAYS", "5"))
TASK_TTL_HOURS = int(os.environ.get("TASK_TTL_HOURS", "1"))
# FIDE ratings are published on the 1st of each month — cache for 30 days.
FIDE_RATING_TTL_DAYS = 30

# Precompiled date-header regex (P6).
_DATE_RE = re.compile(r'\[Date "(\d{4})[.\-](\d{2})[.\-](\d{2})"\]')


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
    # Look for Date headers in format [Date "YYYY.MM.DD"] or [Date "YYYY-MM-DD"]
    dates = []

    for match in _DATE_RE.finditer(pgn_text):
        try:
            year, month, day = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            dates.append(datetime(year, month, day, tzinfo=timezone.utc))
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

    days_since_end = (datetime.now(timezone.utc) - end_date).days

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
        cached_at = cached_at.replace(tzinfo=timezone.utc)
        
    ttl = timedelta(hours=CACHE_TTL_HOURS)
    return datetime.now(timezone.utc) - cached_at > ttl


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via .tmp + os.replace (P10)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(str(tmp), str(path))


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

        # Re-evaluate status to catch ongoing→completed transitions (P5).
        # Use stored last_game_date when available to avoid re-parsing PGN.
        last_date = metadata.get("last_game_date")
        if last_date:
            end_dt = datetime.fromisoformat(last_date)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - end_dt).days
            current_status = "completed" if days_since > CACHE_COMPLETED_DAYS else "ongoing"
        else:
            current_status, _ = _determine_tournament_status(pgn_text)
        if metadata.get("status") != current_status:
            metadata["status"] = current_status
            _atomic_write(meta_path, json.dumps(metadata))

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
        _atomic_write(pgn_path, pgn_text)

        # Determine status based on game dates
        status, end_date = _determine_tournament_status(pgn_text)

        metadata = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "tournament_id": tournament_id,
            "url": url,
            "status": status,
        }
        if end_date:
            metadata["last_game_date"] = end_date

        _atomic_write(meta_path, json.dumps(metadata))
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
        pgn_text = pgn_path.read_text()

        # Re-evaluate status from PGN to handle missing or outdated status
        if "status" not in metadata:
            status, _ = _determine_tournament_status(pgn_text)
            metadata["status"] = status
            _atomic_write(meta_path, json.dumps(metadata))

        if _is_expired(metadata):
            _cleanup_expired("players", hash_key)
            return None
        return pgn_text
    except (json.JSONDecodeError, IOError):
        _cleanup_expired("players", hash_key)
        return None


def cache_player(fide_id: str, tournament_id: str, pgn_text: str, status: Optional[str] = None) -> None:
    """Cache filtered PGN for a player-tournament combination.

    Args:
        fide_id: The FIDE ID of the player
        tournament_id: The Lichess tournament ID
        pgn_text: Filtered PGN data to cache
        status: Tournament status ("completed" or "ongoing").
                 If not given, auto-detected from PGN date headers.
                 Completed tournaments are cached indefinitely.
    """
    try:
        key = f"{fide_id}_{tournament_id}"
        hash_key = _get_hash(key)
        pgn_path = _get_pgn_path("players", hash_key)
        meta_path = _get_metadata_path("players", hash_key)

        pgn_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(pgn_path, pgn_text)

        if status is None:
            status, _ = _determine_tournament_status(pgn_text)

        metadata = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "fide_id": fide_id,
            "tournament_id": tournament_id,
            "status": status,
        }
        _atomic_write(meta_path, json.dumps(metadata))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write to cache: {e}")


def cache_task(task_id: str, pgn_text: str, filename: str) -> None:
    """Persist a completed fetch task so its result can be downloaded later.

    Task results are short-lived (TASK_TTL_HOURS) and stored on disk so any
    worker process can serve the download, unblocking horizontal scaling and
    avoiding unbounded in-memory growth.

    Args:
        task_id: Unique task identifier (e.g. a UUID).
        pgn_text: Combined PGN text for download.
        filename: Download filename to present to the client.
    """
    try:
        hash_key = _get_hash(task_id)
        pgn_path = _get_pgn_path("tasks", hash_key)
        meta_path = _get_metadata_path("tasks", hash_key)

        pgn_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(pgn_path, pgn_text)

        metadata = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "filename": filename,
        }
        _atomic_write(meta_path, json.dumps(metadata))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write task to cache: {e}")


def get_cached_task(task_id: str) -> Optional[dict]:
    """Retrieve a persisted fetch task for download.

    Args:
        task_id: Unique task identifier.

    Returns:
        Dict with 'pgn' and 'filename' keys if found and not expired,
        None otherwise. Expired entries are deleted.
    """
    hash_key = _get_hash(task_id)
    meta_path = _get_metadata_path("tasks", hash_key)
    pgn_path = _get_pgn_path("tasks", hash_key)

    if not meta_path.exists() or not pgn_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text())
        pgn_text = pgn_path.read_text()

        cached_at = datetime.fromisoformat(metadata["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - cached_at > timedelta(hours=TASK_TTL_HOURS):
            _cleanup_expired("tasks", hash_key)
            return None

        return {"pgn": pgn_text, "filename": metadata.get("filename", "games.pgn")}
    except (json.JSONDecodeError, IOError, KeyError):
        _cleanup_expired("tasks", hash_key)
        return None


def get_cached_search(query: str) -> Optional[list]:
    """Get cached search results for a player name query.

    Search results are cached permanently (no TTL) since FIDE player data
    changes infrequently.

    Args:
        query: The search query string (case-insensitive).

    Returns:
        Cached list of player dicts if found, None otherwise.
    """
    hash_key = hashlib.md5(query.lower().encode()).hexdigest()[:16]  # MD5 for shorter filenames (search queries are short strings)
    search_dir = Path(CACHE_DIR) / "search"
    json_path = search_dir / f"{hash_key}.json"

    if not json_path.exists():
        return None

    try:
        return json.loads(json_path.read_text())
    except (json.JSONDecodeError, IOError):
        json_path.unlink(missing_ok=True)
        return None


def cache_search(query: str, results: list) -> None:
    """Cache search results for a player name query.

    Args:
        query: The search query string.
        results: List of player dicts with 'fide_id', 'name', 'slug' keys.
    """
    try:
        hash_key = hashlib.md5(query.lower().encode()).hexdigest()[:16]  # MD5 for shorter filenames (search queries are short strings)
        search_dir = Path(CACHE_DIR) / "search"
        json_path = search_dir / f"{hash_key}.json"

        search_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(json_path, json.dumps(results))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write search cache: {e}")


def get_cached_fide_rating(fide_id: str) -> Optional[int]:
    """Get cached FIDE rating for a player.

    FIDE ratings are published on the 1st of each month, so they're cached
    for FIDE_RATING_TTL_DAYS (default 30 days).

    Args:
        fide_id: The FIDE ID of the player.

    Returns:
        Cached rating as int if found and not expired, None otherwise.
    """
    hash_key = hashlib.md5(fide_id.encode()).hexdigest()[:16]
    ratings_dir = Path(CACHE_DIR) / "ratings"
    json_path = ratings_dir / f"{hash_key}.json"

    if not json_path.exists():
        return None

    try:
        data = json.loads(json_path.read_text())
        cached_at = datetime.fromisoformat(data["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - cached_at > timedelta(days=FIDE_RATING_TTL_DAYS):
            json_path.unlink(missing_ok=True)
            return None
        return data["rating"]
    except (json.JSONDecodeError, IOError, KeyError):
        json_path.unlink(missing_ok=True)
        return None


def cache_fide_rating(fide_id: str, rating: int) -> None:
    """Cache FIDE rating for a player.

    Args:
        fide_id: The FIDE ID of the player.
        rating: The Classical FIDE rating.
    """
    try:
        hash_key = hashlib.md5(fide_id.encode()).hexdigest()[:16]
        ratings_dir = Path(CACHE_DIR) / "ratings"
        json_path = ratings_dir / f"{hash_key}.json"

        ratings_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(json_path, json.dumps({
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "fide_id": fide_id,
            "rating": rating,
        }))
    except (OSError, IOError) as e:
        logger.error(f"Failed to write FIDE rating cache: {e}")
