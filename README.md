# Sjakkfangst

**Sjakkfangst** (Norwegian for "Chess Catch" — a chess game hunter) is a Flask web application to fetch chess games for FIDE players from Lichess broadcasts.

## Installation

```bash
uv pip install -r requirements.txt
```

## Running with Podman (Recommended for Security)

For improved security through containerization, run Sjakkfangst in a rootless, hardened container:

```bash
# Build and run (port 5000)
./run-rootless.sh

# Use a different port
HOST_PORT=8080 ./run-rootless.sh

# Adjust resource limits
MEMORY_LIMIT=256m CPU_LIMIT=0.5 ./run-rootless.sh
```

Security features:
- Runs as non-root user
- All Linux capabilities dropped
- Read-only root filesystem
- Resource limits (memory, CPU)
- Isolated network namespace

To verify security settings:
```bash
./verify-security.sh
```

## Caching

Sjakkfangst includes a two-level, file-based caching layer to improve performance and reduce load on Lichess.org:

- **Tournament Cache**: Raw PGN data from Lichess broadcasts is cached for 24 hours (default). Completed tournaments are cached indefinitely.
- **Player Cache**: Filtered games for specific FIDE players are cached for instant subsequent retrieval.

### Cache Configuration

When running with Podman, the cache is persisted on the host in the `./cache` directory. You can configure the caching behavior via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_HOURS` | 1 | Expiration time for ongoing tournaments |
| `HOST_CACHE_DIR` | `./cache` | Host path for persistent storage |

### Logging

Optionally log submitted URLs and cache results to stderr (useful for monitoring in Podman):

| Variable | Default | Description |
|----------|---------|-------------|
| `SJAKKFANGST_LOG_URLS` | *(disabled)* | Set to `1` to enable logging |

When enabled, each fetch request produces output like:

```
[2026-05-01T12:34:56] URL: https://lichess.org/fide/1503014/Carlsen_Magnus  fide: 1503014  name: Carlsen_Magnus
[2026-05-01T12:34:57] [1/12] Tata Steel Chess 2026 - player cache hit
[2026-05-01T12:34:57] [2/12] Norway Chess 2026 - tournament cache hit
[2026-05-01T12:35:00] [3/12] Sinquefield Cup 2026 - downloaded
[2026-05-01T12:35:10] done: Carlsen_Magnus — 47 games
```

Enable with Podman:
```bash
SJAKKFANGST_LOG_URLS=1 ./run-rootless.sh
```

## Usage (Direct)

If not using Podman, run the Flask application directly:

1. Run the Flask application:
```bash
python app.py
```

2. Open your browser to `http://localhost:5000`

3. Enter a [Lichess FIDE player URL](https://lichess.org/fide) in the format:
   `https://lichess.org/fide/{fide_id}/{player_name}`
   Example: `https://lichess.org/fide/1503014/Carlsen_Magnus`

4. The app will download all broadcast games for that player, showing real-time progress for each tournament. You can expand the details to see exactly which tournaments are being processed and which ones are being retrieved from the cache (marked as "(cached)").

5. Once finished, a PGN file containing all games will be downloaded automatically.

## Project Structure

- `app.py` - Flask web application entry point
- `scraper.py` - URL parsing and broadcast fetching
- `pgn_processor.py` - PGN download and filtering
- `cache.py` - Disk-based caching with TTL and status detection
- `templates/index.html` - Web interface
- `tests/` - Unit tests
- `Containerfile` - Podman/Docker container definition
- `run-rootless.sh` - Rootless container run script with hardening
- `verify-security.sh` - Security verification script

## Testing

Run tests with:
```bash
python -m pytest tests/ -v
```

## Requirements

- Python 3.8+
- See `requirements.txt` for dependencies
