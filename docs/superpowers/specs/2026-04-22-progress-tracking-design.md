# Progress Tracking Design

## Overview

Sjakkfangst uses Server-Sent Events (SSE) to provide a rich, real-time user experience during the game fetching process. This allows users to see exactly which tournaments are being processed, which ones are cached, and the overall progress.

## Goals

- Provide immediate feedback to the user after submitting a URL.
- Show detailed progress for each tournament being fetched.
- Indicate which results are being retrieved from the cache.
- Handle long-running processes without browser timeouts.
- Automatically trigger the file download once all processing is complete.

## Architecture

### SSE Stream Protocol

The backend at `/fetch_stream` yields `text/event-stream` data. Each message is a JSON object:

1. **Initial List**: `{"tournaments": ["Name 1", "Name 2", ...]}`
   - Sent once at the start.
2. **Progress Update**: `{"index": 0, "progress": 5, "name": "Name 1", "cached": true}`
   - Sent for each tournament.
   - `index`: The 0-based index of the tournament in the initial list.
   - `progress`: Overall percentage (0-100).
   - `name`: Human-readable tournament name.
   - `cached`: Boolean indicating if a cache hit occurred.
3. **Completion**: `{"progress": 100, "done": true, "id": "task-uuid"}`
   - Sent when all tournaments are processed.
   - `id`: UUID to retrieve the final combined PGN.
4. **Error**: `{"error": "Description"}`
   - Sent if something fails.

### UI Components

- **Progress Bar**: Visual representation of `data.progress`.
- **Status Text**: Concise description of the current action (e.g., "Fetching: Tournament X").
- **Tournament Details**: A `<details>` element containing a list (`<ul>`) of all tournaments.
  - **Status Icons**:
    - `○`: Pending
    - `▶`: Active/Processing
    - `✓`: Completed
  - **Cache Indicator**: `(cached)` label next to tournament names retrieved from cache.
  - **Auto-expansion**: The details section opens automatically on submission.
  - **Smooth Scrolling**: The active tournament is scrolled into view.

## Implementation Details

### Backend (Flask)

The `fetch_stream` route uses a generator function to yield events. Key headers are set to ensure real-time delivery:
- `Cache-Control: no-cache, no-store, must-revalidate`
- `X-Accel-Buffering: no` (Critical for Nginx/proxies)

### Frontend (JavaScript)

The frontend uses the `EventSource` API. To prevent browser caching of the SSE stream itself, a cache-buster timestamp is added to the URL:
```javascript
new EventSource(`/fetch_stream?url=...&t=${Date.now()}`)
```

Update logic relies on the `index` provided by the server to identify the correct `<li>` element in the tournament list, ensuring the first entry and all subsequent ones are updated correctly even if names are similar.

## Error Handling

- **Connection Error**: `onerror` handler in the frontend detects if the stream is interrupted and shows a user-friendly error message.
- **Server-Side Errors**: Caught in the backend generator and sent as an `error` event, which the client displays before closing the connection.
- **Rate Limiting**: The backend includes `time.sleep(3)` between downloads (if not cached) to respect Lichess API rate limits.

---

*Design approved: 2026-04-22*
