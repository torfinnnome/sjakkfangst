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

# Adjust memory limit
MEMORY_LIMIT=256m ./run-rootless.sh

# Run in background (detached)
./run-rootless.sh --background
```

> CPU limits (`--cpus`) are not enabled by default because they require kernel cgroup delegation setup (uncommon on most distributions). Memory limits work fine in rootless mode.

Security features:
- Runs as non-root user
- All Linux capabilities dropped
- Read-only root filesystem
- Resource limits (memory)
- Isolated network namespace

To verify security settings:
```bash
./verify-security.sh
```

## Caching

Sjakkfangst includes a file-based caching layer to improve performance and reduce load on Lichess.org:

- **Tournament Cache**: Raw PGN data from Lichess broadcasts. Ongoing tournaments are cached for 1 hour (default); completed tournaments are cached indefinitely.
- **Player Cache**: Filtered games for specific FIDE players are cached for instant subsequent retrieval.
- **Task Cache**: Completed fetch results are stored on disk (1 hour TTL) so any worker process can serve the download, unblocking horizontal scaling.

### Cache Configuration

When running with Podman, the cache is persisted on the host in the `./cache` directory. Configure via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_HOURS` | 1 | Expiration time for ongoing tournaments |
| `CACHE_COMPLETED_DAYS` | 5 | Days after a tournament's last game before it's treated as `completed` (indefinite TTL) |
| `TASK_TTL_HOURS` | 1 | Expiration time for completed fetch task results |
| `HOST_CACHE_DIR` | `./cache` | Host path for persistent storage (Podman only) |

### Scraper Configuration

Sjakkfangst paginates through Lichess FIDE player pages to find all broadcast tournaments. To avoid excessive requests, the number of tournaments is capped:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_BROADCASTS` | 100 | Maximum tournaments to fetch per player (~4–5 pages) |

### Download & Performance Configuration

Tournaments that aren't in cache are downloaded concurrently with a shared rate limiter that keeps requests polite to Lichess:

| Variable | Default | Description |
|----------|---------|-------------|
| `DOWNLOAD_WORKERS` | 3 | Concurrent download workers for uncached tournaments |
| `LICHESS_MIN_SPACING` | 2 | Minimum seconds between Lichess download requests (shared across workers) |
| `RETRY_ATTEMPTS` | 3 | HTTP retry attempts for transient errors |
| `RETRY_DELAY` | 2 | Seconds between retry attempts |

### Rate Limiting

Incoming requests are rate-limited per client IP (2/minute) and globally (6/minute) to protect the service. When limited, the UI shows a countdown and re-enables the form automatically.

### Logging

Optionally log submitted URLs and cache results to stderr (useful for monitoring in Podman):

| Variable | Default | Description |
|----------|---------|-------------|
| `SJAKKFANGST_LOG_URLS` | *(disabled)* | Set to `1` to enable logging |

When enabled, each fetch request produces a single line of output:

```
[2026-05-01T12:34:56] https://lichess.org/fide/1503014/Carlsen_Magnus  Carlsen_Magnus (1503014)  12 tours  p=5 t=4 d=3  = 47 games
```

The counters indicate: `p` = player cache hit, `t` = tournament cache hit, `d` = downloaded.

**Privacy note:** When enabled, logs contain FIDE IDs and player names (semi-public data from Lichess). Ensure stderr/journald access is restricted appropriately.

Enable with Podman:
```bash
SJAKKFANGST_LOG_URLS=1 ./run-rootless.sh
```

### Systemd Service with Podman Quadlet

Podman Quadlets are a simple, declarative way to define containers as systemd services. The Quadlet files are translated into proper systemd units automatically. This approach uses rootless podman — no sudo required.

**1. Build the image:**

```bash
podman build -t sjakkfangst:latest -f Containerfile .
```

**2. Create the Quadlet directory:**

```bash
mkdir -p ~/.config/containers/systemd
```

**3. Create the container Quadlet:**

```bash
cat > ~/.config/containers/systemd/sjakkfangst.container << 'EOF'
[Unit]
Description=Sjakkfangst Chess Game Hunter
After=network-online.target

[Container]
Image=localhost/sjakkfangst:latest
PublishPort=127.0.0.1:5000:5000
Volume=/path/to/sjakkfangst/cache:/cache:Z
EnvironmentFile=/path/to/sjakkfangst/.env
DropCapability=ALL
NoNewPrivileges=true
ReadOnly=true
Tmpfs=/tmp:noexec,nosuid,size=100m
Memory=512m
UserNS=keep-id

[Install]
WantedBy=default.target
EOF
```

Replace `/path/to/sjakkfangst` with the absolute path to your project directory (e.g., `/home/youruser/code/sjakkfangst`). The cache directory will be persisted on the host.

Optionally create a `.env` file in your project directory for additional environment variables:

```bash
cat > /path/to/sjakkfangst/.env << 'EOF'
CACHE_DIR=/cache
CACHE_TTL_HOURS=1
CACHE_COMPLETED_DAYS=5
TASK_TTL_HOURS=1
MAX_BROADCASTS=100
DOWNLOAD_WORKERS=3
LICHESS_MIN_SPACING=2
RETRY_ATTEMPTS=3
RETRY_DELAY=2
SJAKKFANGST_LOG_URLS=1
EOF
```

**4. Enable lingering (so it starts at boot, not just at login):**

```bash
loginctl enable-linger $USER
```

**5. Start the service:**

```bash
systemctl --user daemon-reexec
systemctl --user start sjakkfangst.service
```

Note: The service name is `sjakkfangst.service` (not `sjakkfangst.container.service`). Generated Quadlet units cannot be `enable`d — the `[Install]` section in the Quadlet handles automatic starting.

**6. Verify:**

```bash
systemctl --user status sjakkfangst.service
```

The container starts at boot and restarts on failure. The cache is persisted in the `./cache` directory. The application will be accessible at `http://localhost:5000`.

**Manage the service:**

```bash
systemctl --user stop sjakkfangst.service
systemctl --user start sjakkfangst.service
systemctl --user restart sjakkfangst.service
journalctl --user -u sjakkfangst.service -f
```

## Usage (Direct)

If not using Podman, run the app directly:

1. Start the Flask application:
```bash
python app.py
```

> For production-like runs, use `gunicorn --workers 2 --threads 8 --timeout 600 --bind 0.0.0.0:5000 app:app` (this is what the container uses). The built-in `python app.py` is fine for quick local development.

2. Open your browser to `http://localhost:5000`

3. Enter a [Lichess FIDE player URL](https://lichess.org/fide) in the format:
   `https://lichess.org/fide/{fide_id}/{player_name}`
   Example: `https://lichess.org/fide/1503014/Carlsen_Magnus`

4. The app will download all broadcast games for that player, showing real-time progress for each tournament. Expand the details to see which tournaments are being processed and which are retrieved from the cache (marked as "(cached)").

5. Once finished, an **Opening Statistics** summary appears (games, wins/draws/losses, win rate, average opponent Elo per opening, sortable by clicking column headers), along with a **Download PGN** button to save the combined games.

## Project Structure

- `app.py` - Flask web application entry point (SSE streaming, parallel downloads)
- `scraper.py` - URL parsing and broadcast fetching with pagination
- `pgn_processor.py` - PGN download, filtering by FIDE ID, and opening stats
- `cache.py` - Disk-based caching with TTL and tournament status detection
- `rate_limit.py` - In-memory per-IP and global rate limiter
- `templates/index.html` - Web interface
- `tests/` - Unit and HTTP-layer tests
- `Containerfile` - Podman/Docker container definition (gunicorn runtime)
- `run-rootless.sh` - Rootless container run script with hardening
- `verify-security.sh` - Security verification script

## Testing

Run tests with:
```bash
python -m pytest tests/ -v
```

## Requirements

- Python 3.9+
- See `requirements.txt` for dependencies
