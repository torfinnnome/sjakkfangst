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

# Check cache is writable
if podman exec "$CONTAINER_NAME" touch /cache/.writable 2>/dev/null; then
    echo "✓ PASS: Cache directory is writable"
    podman exec "$CONTAINER_NAME" rm /cache/.writable 2>/dev/null
else
    echo "✗ FAIL: Cache directory is not writable"
    exit 1
fi

echo ""
echo "=== All security checks passed ==="
