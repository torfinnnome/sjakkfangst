#!/bin/bash
set -euo pipefail

CONTAINER_NAME="sjakkfangst"
IMAGE_NAME="sjakkfangst:latest"
HOST_PORT="${HOST_PORT:-5000}"
MEMORY_LIMIT="${MEMORY_LIMIT:-512m}"
CPU_LIMIT="${CPU_LIMIT:-auto}"

# Auto-detect if CPU cgroup controller is available (for rootless)
cpu_controller_available() {
    local controllers=""
    
    # Check user cgroup controllers if available
    local user_cgroup="/sys/fs/cgroup/user.slice/user-$(id - u).slice/cgroup.controllers"
    if [[ -f "$user_cgroup" ]]; then
        controllers=$(cat "$user_cgroup" 2>/dev/null || true)
    fi
    
    # Fallback: check root cgroup
    if [[ -z "$controllers" && -f /sys/fs/cgroup/cgroup.controllers ]]; then
        controllers=$(cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null || true)
    fi
    
    [[ "$controllers" == *cpu* ]]
}

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

# Build podman run command
PODMAN_ARGS=(
    --name "$CONTAINER_NAME"
    --rm
    -p "$HOST_PORT:5000"
    -u 1000:1000
    --cap-drop=ALL
    --security-opt=no-new-privileges
    --read-only
    --tmpfs /tmp:noexec,nosuid,size=100m
    --memory="$MEMORY_LIMIT"
    --log-driver=journald
    --log-opt=tag="{{.Name}}"
)

# Handle CPU limit
case "$CPU_LIMIT" in
    auto|1.0)
        # Auto mode: try to apply if available, otherwise skip silently
        if cpu_controller_available; then
            echo "  CPU limit: 1.0"
            PODMAN_ARGS+=(--cpus="1.0")
        fi
        ;;
    "")
        # Empty: explicitly disabled
        ;;
    *)
        # Explicit value: check availability
        if cpu_controller_available; then
            echo "  CPU limit: $CPU_LIMIT"
            PODMAN_ARGS+=(--cpus="$CPU_LIMIT")
        else
            echo "  CPU limit: $CPU_LIMIT (WARNING: cpu controller not available, skipping)"
        fi
        ;;
esac

echo ""
echo "Press Ctrl+C to stop"

exec podman run "${PODMAN_ARGS[@]}" "$IMAGE_NAME"
