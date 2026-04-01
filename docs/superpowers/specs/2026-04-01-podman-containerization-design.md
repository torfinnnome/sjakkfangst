# Sjakkfangst Podman Containerization Design

## Overview

Containerize the Sjakkfangst Flask application using Podman with a rootless, security-hardened configuration.

## Goals

- Run the application in an isolated container environment
- Use rootless containers for improved security
- Apply security hardening: non-root user, dropped capabilities, read-only filesystem
- Maintain application functionality without changes to core logic

## Non-Goals

- Database persistence (in-memory task storage is acceptable)
- HTTPS/TLS termination (handled at reverse proxy level if needed)
- Multi-container orchestration (single container deployment)

## Architecture

### Components Created

1. **Containerfile** — Multi-stage build producing a minimal runtime image
2. **run-rootless.sh** — Wrapper script for launching with security flags and error handling

### Base Image

- **Build stage**: `python:3.12-alpine` with build dependencies
- **Runtime stage**: `python:3.12-alpine` (Alpine Linux ~50MB)
- Alternative considered: `python:3.12-slim` (Debian-based ~120MB), Alpine chosen for smaller footprint

### Security Model

| Hardening Measure | Implementation |
|------------------|----------------|
| Rootless execution | `-u 1000:1000` flag |
| Capability dropping | `--cap-drop=ALL` |
| No new privileges | `--security-opt=no-new-privileges` |
| Read-only filesystem | `--read-only` flag |
| Writable tmpfs | `--tmpfs /tmp` for temporary files |
| Minimal image | Alpine base with only runtime dependencies |

## Data Flow

No changes to application data flow:

1. User submits Lichess FIDE URL via browser → Container port 5000
2. Container fetches from Lichess API → Outbound HTTPS (allowed)
3. Container returns PGN file → Browser download
4. In-memory task storage persists for duration of request cycle

## File Structure

```
.
├── Containerfile          # Multi-stage container build definition
├── run-rootless.sh        # Podman run script with hardening and error handling
├── app.py                 # Compatible (no changes required)
├── scraper.py             # Unchanged
├── pgn_processor.py       # Unchanged
├── templates/
│   └── index.html         # Unchanged
└── requirements.txt       # Unchanged
```

## Implementation Details

### Containerfile

```dockerfile
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

# Install runtime dependencies
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

# Copy application code
COPY --chown=appuser:appuser app.py scraper.py pgn_processor.py ./
COPY --chown=appuser:appuser templates/ ./templates/

# Switch to non-root user
USER appuser

# Expose Flask port
EXPOSE 5000

# Health check using Flask's built-in server
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:5000/ || exit 1

# Run Flask application
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]
```

### run-rootless.sh

```bash
#!/bin/bash
set -euo pipefail

CONTAINER_NAME="sjakkfangst"
IMAGE_NAME="sjakkfangst:latest"
HOST_PORT="${HOST_PORT:-5000}"
MEMORY_LIMIT="${MEMORY_LIMIT:-512m}"
CPU_LIMIT="${CPU_LIMIT:-1.0}"

# Error handler function
cleanup() {
    if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
        echo "Cleaning up container..."
        podman stop "$CONTAINER_NAME" 2>/dev/null || true
        podman rm -f "$CONTAINER_NAME" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Check if port is already in use
if lsof -Pi :"$HOST_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Error: Port $HOST_PORT is already in use."
    echo "Either stop the existing service or set a different port:"
    echo "  HOST_PORT=5001 ./run-rootless.sh"
    exit 1
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
echo "  CPU limit: $CPU_LIMIT"
echo ""
echo "Press Ctrl+C to stop"

exec podman run \
    --name "$CONTAINER_NAME" \
    --rm \
    -p "$HOST_PORT:5000" \
    -u 1000:1000 \
    --cap-drop=ALL \
    --security-opt=no-new-privileges \
    --read-only \
    --tmpfs /tmp:noexec,nosuid,size=100m \
    --memory="$MEMORY_LIMIT" \
    --cpus="$CPU_LIMIT" \
    --log-driver=journald \
    --log-opt=tag="{{.Name}}" \
    "$IMAGE_NAME"
```

### app.py Changes

No changes required. The Containerfile sets `CMD` with `--host=0.0.0.0` flag, making Flask listen on all interfaces for container networking.

**Verification**: Current `app.py` uses `debug=True` in `if __name__ == "__main__"` block, which is bypassed when running via `python -m flask` with explicit `--host` flag.

### Dependency Compatibility

All dependencies are pure Python libraries compatible with Alpine Linux:
- `flask` — Pure Python
- `beautifulsoup4` — Pure Python
- `requests` — Pure Python (certifi for certs included)
- `python-chess` — Pure Python (no native C extensions)
- `pytest` — Development dependency, not in runtime image

No additional Alpine packages required beyond `wget` for healthchecks.

## Testing Plan

1. **Build test**: `podman build -t sjakkfangst -f Containerfile .`
   - Expected: Build completes without errors
   - Image size: ~50-70MB

2. **Run test**: `./run-rootless.sh`
   - Expected: Container starts on port 5000
   - Error handling: Port conflict detection, build failure messages

3. **Health check**: `curl http://localhost:5000`
   - Expected: Returns HTTP 200 with HTML content containing "Sjakkfangst"

4. **Feature test**: Submit valid Lichess URL, verify PGN download
   - Expected: Progress bar appears, PGN file downloads successfully

5. **Security verification** (run while container is running):
   ```bash
   #!/bin/bash
   # verify-security.sh - Run while container is active
   
   echo "=== Security Verification ==="
   
   # Check user is non-root
   USER_ID=$(podman exec sjakkfangst id -u 2>/dev/null || echo "FAIL")
   if [ "$USER_ID" = "1000" ]; then
       echo "PASS: Running as uid=1000"
   else
       echo "FAIL: Expected uid=1000, got $USER_ID (container may not be running)"
       exit 1
   fi
   
   # Check capabilities
   CAPS=$(podman top sjakkfangst capeff 2>/dev/null | wc -l)
   if [ "$CAPS" -le 1 ]; then
       echo "PASS: No effective capabilities"
   else
       echo "FAIL: Capabilities found"
       exit 1
   fi
   
   # Check filesystem is read-only
   RO=$(podman inspect sjakkfangst --format='{{.HostConfig.ReadonlyRootfs}}' 2>/dev/null)
   if [ "$RO" = "true" ]; then
       echo "PASS: Root filesystem is read-only"
   else
       echo "FAIL: Filesystem is not read-only"
       exit 1
   fi
   
   echo "=== All checks passed ==="
   ```
   **Note:** Container uses `--rm` flag (auto-removes on exit). Keep container running during verification.

6. **Resource limit test**:
   - `podman stats sjakkfangst`
   - Expected: Memory <512MB, CPU < 100%

## Deployment Options

### Option 1: Direct Podman (Default)
```bash
./run-rootless.sh
```

### Option 2: Direct Podman with Custom Settings
```bash
HOST_PORT=8080 MEMORY_LIMIT=256m CPU_LIMIT=0.5 ./run-rootless.sh
```

### Option 3: Systemd Service (Rootless)
```bash
# Generate systemd unit
podman generate systemd --name sjakkfangst --files

# Enable user service
systemctl --user enable container-sjakkfangst.service
systemctl --user start container-sjakkfangst.service
```

## Error Handling

### Port Conflicts
- **Detection**: Script checks if target port is in use before starting
- **Recovery**: User can specify alternative port via `HOST_PORT` environment variable
- **Message**: Clear error message with remediation instructions

### Container Start Failures
- **Detection**: Build and run commands use `set -euo pipefail` for strict error handling
- **Recovery**: Trap handler ensures cleanup on script termination
- **Exit codes**: Non-zero exit on any failure for automation compatibility

### Build Failures
- **Detection**: Explicit check for `podman build` exit code
- **Message**: "Error: Container image build failed" with context
- **Logs**: Podman build output streamed to terminal for debugging

### Memory Exhaustion
- **Detection**: Container exits with OOMKilled status
- **Prevention**: `--memory` limit prevents host resource exhaustion
- **Recovery**: Increase `MEMORY_LIMIT` environment variable

### Network Failures
- **Detection**: Flask request exceptions during Lichess API calls
- **Graceful degradation**: SSE sends error message to client
- **Retry**: Application handles retries at code level (existing behavior)

## Security Considerations

- **Network**: Outbound HTTPS allowed via standard container networking; no inbound restrictions needed (port mapping handles ingress at host level)
- **Filesystem**: Read-only root prevents runtime modifications; `/tmp` is isolated tmpfs with size limits and noexec/nosuid
- **User**: Container runs as UID 1000 inside container namespace; host mapping depends on rootless Podman subuid/subgid configuration (default: container uid 1000 maps to host user's uid for isolated namespaces)
- **Capabilities**: Zero capabilities granted via `--cap-drop=ALL`
- **Privileged escalation**: Prevented via `--security-opt=no-new-privileges`
- **Resource limits**: Memory and CPU constraints prevent DoS
- **Logging**: Journald log driver with container name tagging; logs managed by systemd journal rotation
- **Image security**: Multi-stage build reduces attack surface; Alpine minimal base

## Rollback Plan

To revert to non-containerized deployment:
```bash
podman stop sjakkfangst
podman rm sjakkfangst
python app.py  # Original deployment
```

## Future Enhancements

- Consider rootless k3s/kubernetes deployment for orchestration
- Add container image signing and verification
- Podman Quadlet integration for systemd-native service management (Podman 4.0+)

---

*Design approved: 2026-04-01*
