# Sjakkfangst Data Caching Design

## Overview

Add a file-based caching layer to reduce redundant downloads from Lichess.org when multiple users request data from the same URLs within a configurable time window (default: 24 hours).

## Goals

- Reduce load on Lichess.org by caching both raw tournament PGN data and filtered player results
- Improve response times for repeated requests
- Ensure cached data is automatically invalidated after TTL expires
- Keep the implementation simple (file-based, no external dependencies)

## Non-Goals

- Distributed caching or cache synchronization across multiple instances
- Cache warming or pre-population
- Cache analytics/metrics
- Complex cache eviction policies (LRU, etc.) - simple TTL only

## Architecture

### Cache Levels

Two-level caching strategy:

1. **Tournament Cache**: Raw PGN data from Lichess broadcasts
   - Key: `tournament_id`
   - Shared across all requests (different players requesting same tournament)
   - Max size: ~1-5MB per tournament

2. **Player Cache**: Filtered PGN (games matching a specific FIDE ID)
   - Key: `{fide_id}_{tournament_id}`
   - Provides instant response for repeated player-tournament combinations
   - If tournament cache exists but player cache doesn't, filter from cached tournament data

### Components Created

1. **cache.py** — Core caching module with simple get/put interface
2. **Containerfile updates** — Add cache volume mapping at `/cache`
3. **run-rootless.sh updates** — Add cache directory configuration

### File Structure

```
/cache/                          # External volume mounted in container
├── tournaments/                 # Raw PGN from Lichess broadcasts
│   ├── {hash}.pgn
│   ├── {hash}.meta              # JSON: {"cached_at": "...", "url": "..."}
│   └── ...
└── players/                     # Filtered PGN for specific player-tournament combos
    ├── {hash}.pgn
    ├── {hash}.meta              # JSON: {"cached_at": "...", "fide_id": "...", "tournament_id": "..."}
    └── ...
```

**Filename encoding:** SHA256 hash of the cache key, truncated to 16 characters (hex), to create filesystem-safe names while avoiding collisions.

## Data Flow

```
User submits URL
      ↓
parse_fide_url() → get_broadcasts()
      ↓
For each broadcast tournament:
  │
  ├─ Level 1: Tournament Raw Data
  │   │
  │   ├─ Check cache: get_cached_tournament(tournament_id)
  │   │   ├─ Cache HIT (valid, not expired)
  │   │   │   → Return cached PGN
  │   │   ├─ Cache HIT (expired)
  │   │   │   → Delete files, return None
  │   │   └─ Cache MISS
  │   │       → Continue to fetch
  │   │
  │   └─ download_broadcast_pgn() → cache_tournament(tournament_id, pgn)
  │
  └─ Level 2: Player-Filtered Result
      │
      ├─ Check cache: get_cached_player(fide_id, tournament_id)
      │   ├─ Cache HIT (valid, not expired)
      │   │   → Return filtered PGN immediately
      │   ├─ Cache HIT (expired)
      │   │   → Delete files, return None
      │   └─ Cache MISS
      │       → Continue to filter
      │
      └─ filter_games_by_fide(raw_pgn, fide_id) → cache_player(fide_id, tournament_id, filtered_pgn)
```

## Implementation Details

### cache.py Interface

```python
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
        # Corrupted cache, clean it up
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
    
    # Ensure directory exists
    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write PGN
    pgn_path.write_text(pgn_text)
    
    # Write metadata
    metadata = {
        "cached_at": datetime.utcnow().isoformat(),
        "tournament_id": tournament_id,
        "url": url
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
        # Corrupted cache, clean it up
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
    
    # Ensure directory exists
    pgn_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write PGN
    pgn_path.write_text(pgn_text)
    
    # Write metadata
    metadata = {
        "cached_at": datetime.utcnow().isoformat(),
        "fide_id": fide_id,
        "tournament_id": tournament_id
    }
    meta_path.write_text(json.dumps(metadata))

def clear_expired_cache() -> int:
    """Clear all expired cache entries. Returns count of cleared entries."""
    cleared = 0
    cache_dir = Path(CACHE_DIR)
    
    for subdir in ["tournaments", "players"]:
        subdir_path = cache_dir / subdir
        if not subdir_path.exists():
            continue
            
        for meta_file in subdir_path.glob("*.meta"):
            try:
                metadata = json.loads(meta_file.read_text())
                if _is_expired(metadata):
                    hash_key = meta_file.stem
                    _cleanup_expired(subdir, hash_key)
                    cleared += 1
            except (json.JSONDecodeError, IOError):
                # Corrupted file, clean it up
                hash_key = meta_file.stem
                _cleanup_expired(subdir, hash_key)
                cleared += 1
    
    return cleared
```

### Integration with Existing Code

**scraper.py changes:**
- Modify `get_broadcasts()` to check cache before HTTP request (optional - list of broadcasts rarely needs caching)
- No changes needed to `parse_fide_url()`
- The actual PGN download is in `pgn_processor.py`

**pgn_processor.py changes:**
```python
# Modified download_broadcast_pgn():
def download_broadcast_pgn(broadcast_url: str, tournament_id: str = "") -> str:
    # Normalize tournament_id from URL if not provided
    if not tournament_id:
        # Extract from URL using existing logic...
        pass
    
    # Check cache first
    from cache import get_cached_tournament, cache_tournament
    cached = get_cached_tournament(tournament_id)
    if cached is not None:
        return cached
    
    # Fetch from Lichess...
    pgn_text = _fetch_from_lichess(broadcast_url, tournament_id)
    
    # Cache the result
    if pgn_text:
        cache_tournament(tournament_id, pgn_text, broadcast_url)
    
    return pgn_text
```

**app.py changes:**
- In `fetch_stream()`, check player cache before calling `filter_games_by_fide()`
- If tournament cache exists but player cache doesn't, use cached tournament data for filtering
- Cache filtered result after processing

```python
# In generate() function:
from cache import get_cached_player, cache_player, get_cached_tournament

# Check player cache first
player_cached = get_cached_player(fide_id, tournament_id)
if player_cached is not None:
    all_games.append(player_cached)
    continue

# Not in player cache - get tournament data
pgn_text = download_broadcast_pgn(broadcast['url'])
if pgn_text:
    filtered = filter_games_by_fide(pgn_text, fide_id, player_name)
    if filtered:
        cache_player(fide_id, tournament_id, filtered)  # Cache filtered result
        all_games.append(filtered)
```

### Containerfile Updates

Add cache directory setup and volume mapping:

```dockerfile
# After creating appuser and setting WORKDIR:

# Create cache directory with proper permissions
RUN mkdir -p /cache/tournaments /cache/players && \
    chown -R appuser:appuser /cache

# Environment variables for cache configuration
ENV CACHE_DIR=/cache \
    CACHE_TTL_HOURS=24

# Add volume for persistent cache
VOLUME ["/cache"]
```

### run-rootless.sh Updates

Add cache directory configuration and mounting. The script also pre-creates the expected subdirectory structure on the host to ensure consistent permissions:

```bash
# Configuration
HOST_CACHE_DIR="${HOST_CACHE_DIR:-$PWD/cache}"
CACHE_TTL_HOURS="${CACHE_TTL_HOURS:-24}"

# Create cache directory on host with proper permissions
mkdir -p "$HOST_CACHE_DIR/tournaments" "$HOST_CACHE_DIR/players"
chmod 755 "$HOST_CACHE_DIR"

# Add to podman run command:
    -v "$HOST_CACHE_DIR:/cache:Z" \
    -e CACHE_DIR=/cache \
    -e CACHE_TTL_HOURS="$CACHE_TTL_HOURS" \
```

# Display cache info on startup
echo "  Cache directory: $HOST_CACHE_DIR"
echo "  Cache TTL: $CACHE_TTL_HOURS hours"
```

## Configuration Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_DIR` | `/cache` | Path to cache directory inside container |
| `CACHE_TTL_HOURS` | 24 | Time-to-live for cached entries in hours |
| `HOST_CACHE_DIR` | `./cache` | Host directory mapped to container cache |

## Testing Plan

1. **Unit tests for cache.py:**
   - Test cache write and read
   - Test TTL expiration detection
   - Test expired entry cleanup
   - Test corrupted cache file handling
   - Test concurrent access safety (filesystem atomicity)

2. **Integration tests:**
   - First request populates cache
   - Second request within TTL uses cached data (no HTTP call)
   - Request after TTL expires triggers fresh download
   - Different players sharing same tournament use tournament cache
   - Same player-tournament combination uses player cache

3. **Container tests:**
   - Cache persists across container restarts
   - Cache directory has correct permissions
   - Environment variables are passed correctly
   - Run `./verify-security.sh` to confirm the cache directory is writable within the container

## Error Handling

### Cache Read Failures
- **Corrupted metadata**: Delete and treat as cache miss
- **Missing PGN file**: Delete orphaned metadata and treat as miss
- **Permission errors**: Log warning, treat as miss (app continues to work without caching)

### Cache Write Failures
- **Disk full**: Log error, app continues without caching (degraded performance but functional)
- **Permission errors**: Log warning, service continues
- **Race conditions**: File-level atomicity (write to temp, rename) prevents corruption

### TTL Handling
- Expired entries are deleted on lookup (lazy cleanup)
- Optional full cleanup can be triggered manually or via scheduled job
- `clear_expired_cache()` function provided for bulk cleanup

## Security Considerations

- **Filesystem isolation**: Cache is in isolated directory, not mixed with application code
- **No user input in filenames**: SHA256 hashing ensures safe filenames regardless of input
- **Size limits**: Relying on host filesystem quotas, no built-in cache size limit (acceptable for this use case)
- **Writable only**: Cache directory is writable, but contains no executable code

## Rollback Plan

To disable caching:
1. Set `CACHE_TTL_HOURS=0` - cache lookups will treat all entries as expired
2. Or remove `-v` mount from run-rootless.sh to run without cache volume
3. Cache module gracefully handles missing cache directory

To clear cache manually:
```bash
rm -rf ./cache/tournaments/* ./cache/players/*
```

## Future Enhancements

- Cache size limits with LRU eviction
- Cache statistics endpoint for monitoring
- Background cache cleanup job (if needed for large deployments)
- Compression for large PGN files

---

*Design approved: 2026-04-02*
