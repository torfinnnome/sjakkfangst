# Data Caching Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a file-based caching layer for Lichess data with TTL support (24h default) to reduce redundant downloads and improve response times.

**Architecture:** Two-level caching: tournament-level (raw PGN) and player-level (filtered PGN). File-based storage with SHA256-hashed filenames and JSON metadata. Automatic TTL expiration on lookup.

**Tech Stack:** Python 3.12, Flask, pathlib, hashlib, json, standard library only for cache module.

---

## File Structure

```
cache.py              # NEW: Core caching module with get/put/ttl logic
pgn_processor.py      # MODIFY: Add cache checks before download
app.py                # MODIFY: Add player cache checks in fetch_stream
Containerfile         # MODIFY: Add cache volume and env vars
run-rootless.sh       # MODIFY: Add cache directory setup and mounting
tests/test_cache.py   # NEW: Unit tests for caching functionality
```

---

## Chunk 1: Core Cache Module

### Task 1.1: Create cache.py with basic structure

**Files:**
- Create: `cache.py`
- Test: `tests/test_cache.py`

- [ ] **Step 1: Write the cache.py module**

Create `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/cache.py`:

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
        "tournament_id": tournament_id
    }
    meta_path.write_text(json.dumps(metadata))
```

- [ ] **Step 2: Write basic test for cache write and read**

Create `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/tests/test_cache.py`:

```python
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
    pgn_data = "[Event \"Test\"]\n1. e4 e5"
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
    pgn_data = "[Event \"Test\"]\n[White \"Player1\"]\n1. d4 d5"
    
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
```

- [ ] **Step 3: Run tests to verify basic functionality**

Run: `cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst && python -m pytest tests/test_cache.py::test_get_hash tests/test_cache.py::test_cache_tournament_and_get tests/test_cache.py::test_get_cached_tournament_not_found tests/test_cache.py::test_cache_player_and_get -v`

Expected: 4 PASSED

- [ ] **Step 4: Commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git add cache.py tests/test_cache.py
git commit -m "feat: add cache module with tournament and player caching"
```

### Task 1.2: Add TTL expiration tests

**Files:**
- Test: `tests/test_cache.py` (add to existing file)

- [ ] **Step 1: Write TTL expiration tests**

Add to `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/tests/test_cache.py`:

```python
def test_tournament_expiration(temp_cache_dir):
    """Test that expired tournament cache entries are removed."""
    tournament_id = "expired-tournament"
    pgn_data = "[Event \"Test\"]\n1. e4 e5"
    
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
    pgn_data = "[Event \"Test\"]\n1. c4 c5"
    
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
    pgn_path.write_text("[Event \"Test\"]")
    meta_path.write_text("invalid json {[")
    
    # Should handle gracefully and return None
    result = cache.get_cached_tournament(tournament_id)
    assert result is None
    # Should clean up corrupted files
    assert not pgn_path.exists()
    assert not meta_path.exists()
```

- [ ] **Step 2: Run expiration tests**

Run: `cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst && python -m pytest tests/test_cache.py::test_tournament_expiration tests/test_cache.py::test_player_expiration tests/test_cache.py::test_corrupted_metadata_handling -v`

Expected: 3 PASSED

- [ ] **Step 3: Commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git add tests/test_cache.py
git commit -m "test: add TTL expiration and error handling tests for cache"
```

---

## Chunk 2: Integrate Caching into Scraping Module

### Task 2.1: Modify pgn_processor.py to use tournament cache

**Files:**
- Modify: `pgn_processor.py`
- Test: `tests/test_pgn_processor.py` (existing file)

- [ ] **Step 1: Add cache integration to download_broadcast_pgn**

Modify `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/pgn_processor.py`:

```python
"""PGN processor module for downloading PGN files from broadcasts."""

import io
import re

import chess.pgn
import requests

from cache import get_cached_tournament, cache_tournament


def download_broadcast_pgn(broadcast_url: str) -> str:
    """Download PGN data from a Lichess broadcast URL.
    
    Checks cache first before making HTTP request. Caches successful results.

    Args:
        broadcast_url: A URL in the format https://lichess.org/broadcast/tournament-slug/round-slug/id
                       or https://lichess.org/broadcast/tournament-slug/id

    Returns:
        Raw PGN text from the broadcast, or empty string on error.
    """
    try:
        # Fetch the broadcast page to find the actual tournament ID
        page_response = requests.get(broadcast_url, timeout=30)
        page_response.raise_for_status()

        # The tournament ID is inside the page-init-data JSON in the HTML
        match = re.search(r'"tour":\{"id":"([^"]+)"', page_response.text)
        if match:
            tournament_id = match.group(1)
        else:
            # Fallback: use last path component
            url_parts = broadcast_url.rstrip("/").split("/")
            tournament_id = url_parts[-1]

        # Check cache first
        cached = get_cached_tournament(tournament_id)
        if cached is not None:
            return cached

        # Construct API URL and fetch
        api_url = f"https://lichess.org/api/broadcast/{tournament_id}.pgn"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        pgn_text = response.text
        
        # Cache the result
        if pgn_text:
            cache_tournament(tournament_id, pgn_text, broadcast_url)
        
        return pgn_text
    except requests.RequestException:
        return ""


# filter_games_by_fide function remains unchanged
def filter_games_by_fide(pgn_text: str, fide_id: str, player_name: str = "") -> str:
    """Filter PGN games by FIDE ID or player name.

    Args:
        pgn_text: Raw PGN text containing one or more games.
        fide_id: FIDE ID to filter for (as string).
        player_name: Optional player name slug (e.g. "Carlsen_Magnus") for fallback.

    Returns:
        Filtered PGN text containing matching games.
    """
    # (Keep existing implementation unchanged)
    if not pgn_text:
        return ""

    matching_games = []
    pgn_stream = io.StringIO(pgn_text)
    
    name_variants = []
    if player_name:
        name_variants.append(player_name.lower())
        name_variants.append(player_name.replace("_", " ").lower())
        if "_" in player_name:
            parts = player_name.split("_")
            name_variants.append(f"{parts[0]}, {parts[1]}".lower())

    while True:
        try:
            game = chess.pgn.read_game(pgn_stream)
            if game is None:
                break

            white_fide = game.headers.get("WhiteFideId", "")
            black_fide = game.headers.get("BlackFideId", "")
            is_match = (white_fide == fide_id or black_fide == fide_id)

            if not is_match and name_variants:
                white_name = game.headers.get("White", "").lower()
                black_name = game.headers.get("Black", "").lower()
                for variant in name_variants:
                    if variant in white_name or variant in black_name:
                        is_match = True
                        break

            if is_match:
                exporter = chess.pgn.StringExporter()
                matching_games.append(game.accept(exporter))
        except Exception:
            continue

    return "\n\n".join(matching_games)
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst && python -m pytest tests/test_pgn_processor.py -v`

Expected: All tests PASS (cache is not mocked in existing tests, but they should still work with fresh cache directory)

- [ ] **Step 3: Commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git add pgn_processor.py
git commit -m "feat: add tournament caching to pgn_processor download function"
```

---

## Chunk 3: Integrate Player-Level Caching

### Task 3.1: Modify app.py to use player cache

**Files:**
- Modify: `app.py`
- Test: Run manual verification (existing integration covers the flow)

- [ ] **Step 1: Add player cache integration to fetch_stream**

Modify `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/app.py`:

```python
"""Flask web application for fetching FIDE player games from Lichess broadcasts."""

import io
import json
import time
import uuid
from flask import Flask, render_template, request, send_file, Response

from scraper import parse_fide_url, get_broadcasts
from pgn_processor import download_broadcast_pgn, filter_games_by_fide
from cache import get_cached_player, cache_player

app = Flask(__name__)

# Simple in-memory cache for task results
tasks = {}


@app.route("/", methods=["GET"])
def index():
    """Render the main form for entering FIDE player URL."""
    return render_template("index.html")


@app.route("/fetch_stream", methods=["GET"])
def fetch_stream():
    """Stream progress of PGN fetching as Server-Sent Events."""
    url = request.args.get("url", "").strip()
    if not url:
        return "Error: Please provide a URL", 400

    try:
        player_info = parse_fide_url(url)
    except ValueError as e:
        return f"Error: {e}", 400

    fide_id = player_info["fide_id"]
    player_name = player_info["player_name"]

    def generate():
        # Get list of broadcasts
        broadcasts = get_broadcasts(fide_id, player_name)

        if not broadcasts:
            yield f"data: {json.dumps({'error': 'No broadcasts found'})}\n\n"
            return

        all_games = []
        processed_tournaments = set()
        
        # Deduplicate broadcasts by tournament slug
        unique_broadcasts = []
        seen_slugs = set()
        for b in broadcasts:
            parts = b['url'].split("/")
            if len(parts) < 5:
                continue
            slug = parts[4]
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                unique_broadcasts.append(b)

        total = len(unique_broadcasts)

        for i, broadcast in enumerate(unique_broadcasts):
            name = broadcast['name']
            progress = int((i / total) * 100)
            if progress == 0 and total > 0:
                progress = 1
            
            # Extract tournament_id from URL
            url_parts = broadcast['url'].rstrip("/").split("/")
            tournament_id = url_parts[-1] if len(url_parts) >= 5 else ""

            # Check player cache first
            player_cached = get_cached_player(fide_id, tournament_id)
            is_cached = player_cached is not None

            # Send progress update with cached info
            yield f"data: {json.dumps({'index': i, 'progress': progress, 'name': name, 'cached': is_cached})}\n\n"

            if is_cached:
                if player_cached:
                    all_games.append(player_cached)
                continue

            # Respect Lichess rate limits (only if actually downloading)
            if i > 0:
                time.sleep(3)

            pgn_text = download_broadcast_pgn(broadcast['url'])
            if pgn_text:
                # Pass player_name as fallback for filtering
                filtered = filter_games_by_fide(pgn_text, fide_id, player_name)
                # Cache filtered result for this player
                cache_player(fide_id, tournament_id, filtered)
                if filtered:
                    all_games.append(filtered)

        if not all_games:
            yield f"data: {json.dumps({'error': 'No matching games found'})}\n\n"
            return

        # Success! Store result and notify client
        task_id = str(uuid.uuid4())
        combined_pgn = "\n\n".join(all_games)
        tasks[task_id] = {
            "pgn": combined_pgn,
            "filename": f"{player_name}_fide_games_sjakkfangst.pgn"
        }

        yield f"data: {json.dumps({'progress': 100, 'done': True, 'id': task_id})}\n\n"

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Accel-Buffering"] = "no"  # Disable buffering for Nginx/proxies
    return response


@app.route("/download/<task_id>")
def download(task_id):
    """Download the final PGN file for a completed task."""
    task = tasks.get(task_id)
    if not task:
        return "Task not found or expired", 404

    return send_file(
        io.BytesIO(task["pgn"].encode("utf-8")),
        mimetype="application/x-chess-pgn",
        as_attachment=True,
        download_name=task["filename"],
    )


if __name__ == "__main__":
    app.run(debug=True)
```

- [ ] **Step 2: Verify app imports work**

Run: `cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst && python -c "from app import app; print('Imports OK')"`

Expected: `Imports OK`

- [ ] **Step 3: Commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git add app.py
git commit -m "feat: add player-level caching in fetch_stream endpoint"
```

---

## Chunk 4: Container Configuration

### Task 4.1: Update Containerfile with cache configuration

**Files:**
- Modify: `Containerfile`

- [ ] **Step 1: Add cache directory and environment variables**

Modify `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/Containerfile` (after the USER line, before EXPOSE):

```dockerfile
# Sjakkfangst Flask Application Container
# Multi-stage build for minimal runtime image

# --- Build Stage ---
FROM python:3.12-alpine AS builder

# Install build dependencies
RUN apk add --no-cache gcc musl-dev libffi-dev

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Runtime Stage ---
FROM python:3.12-alpine

# Install runtime dependencies (wget for healthcheck)
RUN apk add --no-cache wget

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Python environment settings for containerized operation
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

# Create non-root user
RUN adduser -D -u 1000 appuser

# Set working directory
WORKDIR /app

# Create cache directory with proper permissions
RUN mkdir -p /cache/tournaments /cache/players && \
    chown -R appuser:appuser /cache

# Environment variables for cache configuration
ENV CACHE_DIR=/cache \
    CACHE_TTL_HOURS=24

# Copy application code
COPY --chown=appuser:appuser app.py scraper.py pgn_processor.py cache.py ./
COPY --chown=appuser:appuser templates/ ./templates/

# Switch to non-root user
USER appuser

# Expose cache directory as volume for persistence
VOLUME ["/cache"]

# Expose Flask port
EXPOSE 5000

# Health check using Flask's built-in server
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:5000/ || exit 1

# Run Flask application
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]
```

- [ ] **Step 2: Verify Containerfile syntax**

Run: `cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst && podman build -t sjakkfangst-test -f Containerfile . --no-cache 2>&1 | head -30`

Expected: Build completes without errors

- [ ] **Step 3: Commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git add Containerfile
git commit -m "feat: add cache volume and environment configuration to Containerfile"
```

---

## Chunk 5: Runtime Script Updates

### Task 5.1: Update run-rootless.sh with cache support

**Files:**
- Modify: `run-rootless.sh`

- [ ] **Step 1: Add cache directory setup and mounting**

Replace `/home/torfinn/code/github.com/torfinnnome/sjakkfangst/run-rootless.sh` with:

```bash
#!/bin/bash
set -euo pipefail

CONTAINER_NAME="sjakkfangst"
IMAGE_NAME="sjakkfangst:latest"
HOST_PORT="${HOST_PORT:-5000}"
MEMORY_LIMIT="${MEMORY_LIMIT:-512m}"

# Cache configuration
HOST_CACHE_DIR="${HOST_CACHE_DIR:-$PWD/cache}"
CACHE_TTL_HOURS="${CACHE_TTL_HOURS:-24}"

# Error handler function
cleanup() {
    if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
        echo "Cleaning up container..."
        podman stop "$CONTAINER_NAME" 2>/dev/null || true
        podman rm -f "$CONTAINER_NAME" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Create cache directory on host with proper permissions
mkdir -p "$HOST_CACHE_DIR"
chmod 755 "$HOST_CACHE_DIR"

# Check if port is already in use
if command -v lsof &> /dev/null; then
    if lsof -Pi :"$HOST_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "Error: Port $HOST_PORT is already in use."
        echo "Either stop the existing service or set a different port:"
        echo "  HOST_PORT=5001 ./run-rootless.sh"
        exit 1
    fi
elif command -v ss &> /dev/null; then
    if ss -tln | grep -q ":$HOST_PORT "; then
        echo "Error: Port $HOST_PORT is already in use."
        echo "Either stop the existing service or set a different port:"
        echo "  HOST_PORT=5001 ./run-rootless.sh"
        exit 1
    fi
fi

# Build if needed
if ! podman image exists "$IMAGE_NAME" 2>/dev/null; then
    echo "Building container image..."
    if ! podman build -t "$IMAGE_NAME" -f Containerfile .; then
        echo "Error: Container image build failed"
        exit 1
    fi
else
    echo "Using existing image: $IMAGE_NAME"
fi

# Remove existing container if running
if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "Removing existing container..."
    podman rm -f "$CONTAINER_NAME" 2>/dev/null || true
fi

echo "Starting Sjakkfangst container on port $HOST_PORT..."
echo "  Memory limit: $MEMORY_LIMIT"
echo "  Cache directory: $HOST_CACHE_DIR"
echo "  Cache TTL: $CACHE_TTL_HOURS hours"
echo ""
echo "Press Ctrl+C to stop"

# Note: CPU limits (--cpus) are not enabled by default because they require
# kernel cgroup delegation setup (uncommon on most distributions).
# Memory limits work fine in rootless mode.
exec podman run \
    --name "$CONTAINER_NAME" \
    --rm \
    --network slirp4netns:allow_host_loopback=true \
    -p "127.0.0.1:$HOST_PORT:5000" \
    -v "$HOST_CACHE_DIR:/cache:Z" \
    -e CACHE_DIR=/cache \
    -e CACHE_TTL_HOURS="$CACHE_TTL_HOURS" \
    -u 1000:1000 \
    --cap-drop=ALL \
    --security-opt=no-new-privileges \
    --read-only \
    --tmpfs /tmp:noexec,nosuid,size=100m \
    --memory="$MEMORY_LIMIT" \
    --log-driver=journald \
    --log-opt=tag="{{.Name}}" \
    "$IMAGE_NAME"
```

- [ ] **Step 2: Verify script is executable**

Run: `chmod +x /home/torfinn/code/github.com/torfinnnome/sjakkfangst/run-rootless.sh && echo "Script is executable"`

Expected: `Script is executable`

- [ ] **Step 3: Commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git add run-rootless.sh
git commit -m "feat: add cache directory mounting and TTL configuration to run script"
```

---

## Final Verification

### Task 6.1: Run all tests

- [ ] **Step 1: Run full test suite**

Run: `cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst && python -m pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 2: Build and test container**

Run: 
```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
podman build -t sjakkfangst:latest -f Containerfile .
```

Expected: Build completes successfully

- [ ] **Step 3: Final commit**

```bash
cd /home/torfinn/code/github.com/torfinnnome/sjakkfangst
git log --oneline -5
```

Expected: Shows commit history with our changes

---

## Summary of Changes

| File | Change Type | Description |
|------|-------------|-------------|
| `cache.py` | Create | Core caching module with TTL support |
| `tests/test_cache.py` | Create | Unit tests for caching functionality |
| `pgn_processor.py` | Modify | Add tournament-level caching to `download_broadcast_pgn()` |
| `app.py` | Modify | Add player-level caching in `fetch_stream()` |
| `Containerfile` | Modify | Add cache volume, env vars, and `cache.py` copy |
| `run-rootless.sh` | Modify | Add cache directory mounting and configuration |

## Testing Checklist

- [ ] Cache write and read operations work correctly
- [ ] TTL expiration removes old entries
- [ ] Corrupted cache files are handled gracefully
- [ ] Tournament cache is checked before HTTP downloads
- [ ] Player cache is checked before filtering
- [ ] Container builds successfully with cache configuration
- [ ] Cache directory persists across container restarts
- [ ] Environment variables configure cache correctly
