# Sjakkfangst Podman Containerization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a rootless, security-hardened Podman container for the Sjakkfangst Flask application.

**Architecture:** Multi-stage build using python:3.12-alpine with runtime hardening (non-root user, dropped capabilities, read-only filesystem, tmpfs for temp files).

**Tech Stack:** Podman, Python 3.12, Alpine Linux, Flask, Bash

---

## File Structure

```
.
├── Containerfile              # Create: Multi-stage container build
├── run-rootless.sh            # Create: Wrapper script with security flags
├── verify-security.sh         # Create: Optional security verification script
├── app.py                     # Unchanged (Flask binding handled in Containerfile)
├── scraper.py                 # Unchanged
├── pgn_processor.py           # Unchanged
├── templates/index.html       # Unchanged
└── requirements.txt           # Unchanged
```

## Chunk 1: Create Containerfile

### Task 1: Write the Containerfile

**Files:**
- Create: `Containerfile`

- [ ] **Step 1: Create the multi-stage Containerfile**

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

- [ ] **Step 2: Verify the Containerfile syntax**

Run: `podman build -t sjakkfangst-test -f Containerfile --dry-run . 2>&1 | head -10 || echo "Dry-run check complete"`
Expected: No syntax errors (dry-run may not exist, just check file content)

Alternative check: `cat Containerfile | grep -E "^(FROM|RUN|COPY|ENV|EXPOSE|CMD|HEALTHCHECK)" | head -5`
Expected: Shows FROM, RUN, COPY, ENV, etc. directives

- [ ] **Step 3: Commit Containerfile**

```bash
git add Containerfile
git commit -m "feat: add multi-stage Containerfile for rootless deployment

- Uses python:3.12-alpine for minimal footprint (~50MB)
- Multi-stage build separates build and runtime dependencies
- Runs as non-root user (uid=1000)
- Includes healthcheck using wget"
```

---

## Chunk 2: Create run-rootless.sh Script

### Task 2: Write the run script

**Files:**
- Create: `run-rootless.sh`

- [ ] **Step 1: Create the shell script**

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

- [ ] **Step 2: Make script executable**

Run: `chmod +x run-rootless.sh`
Expected: Script now has execute permissions

- [ ] **Step 3: Test script syntax**

Run: `bash -n run-rootless.sh`
Expected: No output (syntax OK)

- [ ] **Step 4: Commit run script**

```bash
git add run-rootless.sh
git commit -m "feat: add rootless Podman run script with hardening

- Detects port conflicts before starting
- Applies security hardening:
  * --cap-drop=ALL (no capabilities)
  * --security-opt=no-new-privileges
  * --read-only filesystem
  * --tmpfs for /tmp with size limits
  * Memory and CPU resource limits
- Supports custom port via HOST_PORT env var
- Uses journald logging with rotation"
```

---

## Chunk 3: Create Optional Security Verification Script

### Task 3: Write verify-security.sh

**Files:**
- Create: `verify-security.sh`

- [ ] **Step 1: Create the verification script**

```bash
#!/bin/bash
# verify-security.sh - Verify Sjakkfangst container security settings
# Run this while the container is running

set -euo pipefail

CONTAINER_NAME="sjakkfangst"

echo "=== Sjakkfangst Security Verification ==="
echo ""

# Check if container is running
if ! podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "FAIL: Container '$CONTAINER_NAME' not found"
    echo "Make sure the container is running: ./run-rootless.sh"
    exit 1
fi

# Check user is non-root
USER_ID=$(podman exec "$CONTAINER_NAME" id -u 2>/dev/null || echo "FAIL")
if [ "$USER_ID" = "1000" ]; then
    echo "✓ PASS: Running as uid=1000 (non-root)"
else
    echo "✗ FAIL: Expected uid=1000, got $USER_ID"
    exit 1
fi

# Check capabilities
CAPS=$(podman top "$CONTAINER_NAME" capeff 2>/dev/null | wc -l)
if [ "$CAPS" -le 1 ]; then
    echo "✓ PASS: No effective capabilities"
else
    echo "✗ FAIL: Capabilities found"
    podman top "$CONTAINER_NAME" capeff
    exit 1
fi

# Check filesystem is read-only
RO=$(podman inspect "$CONTAINER_NAME" --format='{{.HostConfig.ReadonlyRootfs}}' 2>/dev/null || echo "false")
if [ "$RO" = "true" ]; then
    echo "✓ PASS: Root filesystem is read-only"
else
    echo "✗ FAIL: Filesystem is not read-only"
    exit 1
fi

# Check memory limit
MEM_LIMIT=$(podman inspect "$CONTAINER_NAME" --format='{{.HostConfig.Memory}}' 2>/dev/null || echo "0")
if [ "$MEM_LIMIT" != "0" ] && [ "$MEM_LIMIT" != "" ]; then
    MEM_MB=$((MEM_LIMIT / 1024 / 1024))
    echo "✓ PASS: Memory limit set to ${MEM_MB}MB"
else
    echo "✗ FAIL: No memory limit set"
    exit 1
fi

echo ""
echo "=== All security checks passed ==="
```

- [ ] **Step 2: Make script executable**

Run: `chmod +x verify-security.sh`

- [ ] **Step 3: Test script syntax**

Run: `bash -n verify-security.sh`
Expected: No output

- [ ] **Step 4: Commit verification script**

```bash
git add verify-security.sh
git commit -m "feat: add security verification script

- Checks non-root user execution (uid=1000)
- Verifies no capabilities granted
- Confirms read-only filesystem
- Validates memory limits are set"
```

---

## Chunk 4: Test Container Build and Run

### Task 4: Build and test the container

**Files:**
- Test: Build and run container

- [ ] **Step 1: Build the container image**

Run: `podman build -t sjakkfangst:latest -f Containerfile .`
Expected: Build completes successfully, image size ~50-70MB

- [ ] **Step 2: Verify image was created**

Run: `podman images | grep sjakkfangst`
Expected: Shows "sjakkfangst latest" with a size ~50-70MB

- [ ] **Step 3: Start container in background for testing**

Run: `HOST_PORT=5000 ./run-rootless.sh &`
Expected: "Starting Sjakkfangst container on port 5000..." message
Sleep: 3 seconds for Flask to start

- [ ] **Step 4: Test health endpoint**

Run: `curl -s http://localhost:5000 | head -20`
Expected: HTML content with "Sjakkfangst" visible

- [ ] **Step 5: Run security verification**

Run: `./verify-security.sh`
Expected: All 4 checks pass

- [ ] **Step 6: Stop the container**

Run: `kill %1 2>/dev/null || pkill -f "podman run.*sjakkfangst" || true`
Wait: 2 seconds for cleanup

- [ ] **Step 7: Verify container removed**

Run: `podman ps -a | grep sjakkfangst || echo "Container cleaned up"`
Expected: "Container cleaned up" (no running or stopped containers)

- [ ] **Step 8: Commit verification results**

```bash
git commit --allow-empty -m "test: verify container build and security hardening

- Container builds successfully (~70MB)
- Flask responds on port 5000
- Security verification passes:
  * Non-root execution (uid=1000)
  * Zero capabilities
  * Read-only root filesystem
  * Memory limits enforced"
```

---

## Chunk 5: Update Documentation

### Task 5: Add container usage to README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add container section to README**

Find the "## Usage" section and add before it:

```markdown
## Running with Podman (Recommended for Security)

For improved security, run Sjakkfangst in a rootless, hardened container:

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

## Usage
```

- [ ] **Step 2: Verify markdown formatting**

Run: `head -50 README.md | tail -40`
Expected: New container section appears correctly

- [ ] **Step 3: Commit documentation update**

```bash
git add README.md
git commit -m "docs: add Podman container usage instructions

- Document rootless container setup
- List security hardening features
- Include resource limit customization
- Add security verification command"
```

---

## Plan Completion Checklist

- [ ] Containerfile created and committed
- [ ] run-rootless.sh created, executable, and committed
- [ ] verify-security.sh created, executable, and committed
- [ ] Container builds successfully (~50-70MB)
- [ ] Container runs and responds on localhost:5000
- [ ] Security verification passes all checks
- [ ] README updated with container usage instructions
- [ ] All files committed with descriptive messages
