#!/bin/bash
set -euo pipefail

CONTAINER_NAME="sjakkfangst"
IMAGE_NAME="sjakkfangst:latest"
HOST_PORT="${HOST_PORT:-5000}"
MEMORY_LIMIT="${MEMORY_LIMIT:-512m}"

# Cache configuration
HOST_CACHE_DIR="${HOST_CACHE_DIR:-$PWD/cache}"
CACHE_TTL_HOURS="${CACHE_TTL_HOURS:-24}"

# Parse arguments
FOREGROUND=true
for arg in "$@"; do
    case "$arg" in
        --background|-b)
            FOREGROUND=false
            ;;
        --help|-h)
            echo "Usage: $0 [--background]"
            echo ""
            echo "Options:"
            echo "  --background, -b   Run container in background (detached)"
            echo "  --help, -h         Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  HOST_PORT          Port to expose (default: 5000)"
            echo "  MEMORY_LIMIT       Container memory limit (default: 512m)"
            echo "  HOST_CACHE_DIR     Cache directory path (default: ./cache)"
            echo "  CACHE_TTL_HOURS    Cache TTL in hours (default: 24)"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            echo "Run with --help for usage"
            exit 1
            ;;
    esac
done

# Error handler function (foreground only)
cleanup() {
    if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
        echo "Cleaning up container..."
        podman stop "$CONTAINER_NAME" 2>/dev/null || true
        podman rm -f "$CONTAINER_NAME" 2>/dev/null || true
    fi
}

# Create cache directory on host with proper permissions
mkdir -p "$HOST_CACHE_DIR"
chmod 755 "$HOST_CACHE_DIR"

# Check if port is already in use
if command -v lsof &> /dev/null; then
    if lsof -Pi :"$HOST_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "Error: Port $HOST_PORT is already in use."
        echo "Either stop the existing service or set a different port:"
        echo "  HOST_PORT=5001 $0"
        exit 1
    fi
elif command -v ss &> /dev/null; then
    if ss -tln | grep -q ":$HOST_PORT "; then
        echo "Error: Port $HOST_PORT is already in use."
        echo "Either stop the existing service or set a different port:"
        echo "  HOST_PORT=5001 $0"
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

if [ "$FOREGROUND" = true ]; then
    echo "Running in foreground (press Ctrl+C to stop)"
    trap cleanup EXIT

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
else
    echo "Running in background (detached)"
    echo ""

    # Note: CPU limits (--cpus) are not enabled by default because they require
    # kernel cgroup delegation setup (uncommon on most distributions).
    # Memory limits work fine in rootless mode.
    podman run \
        --name "$CONTAINER_NAME" \
        --detach \
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

    echo "Container started in background."
    echo ""
    echo "Useful commands:"
    echo "  podman logs -f $CONTAINER_NAME    # View logs"
    echo "  podman stop $CONTAINER_NAME       # Stop container"
    echo "  podman rm -f $CONTAINER_NAME      # Remove container"
fi
