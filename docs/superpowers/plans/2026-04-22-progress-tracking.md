# Progress Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement real-time progress tracking for tournament PGN fetching using Server-Sent Events (SSE).

**Architecture:** The Flask backend streams JSON updates via SSE. The frontend uses `EventSource` to listen for these updates and dynamically updates a progress bar and a detailed tournament list.

**Tech Stack:** Python (Flask SSE), JavaScript (EventSource, DOM manipulation), HTML/CSS.

---

## File Structure

```
app.py                # MODIFY: Implement fetch_stream SSE endpoint
templates/index.html  # MODIFY: Add progress UI and EventSource logic
```

---

## Chunk 1: Backend SSE Implementation

### Task 1.1: Implement fetch_stream in app.py

- [x] **Step 1: Create the generator for SSE updates**
- [x] **Step 2: Include tournament list, progress percentage, and individual tournament status**
- [x] **Step 3: Add cache status and index-based identification for reliability**
- [x] **Step 4: Set appropriate headers to disable buffering (X-Accel-Buffering, Cache-Control)**

## Chunk 2: Frontend UI and Integration

### Task 2.1: Create Progress UI in index.html

- [x] **Step 1: Add progress bar and status text elements**
- [x] **Step 2: Add a collapsible <details> section for tournament-specific status**
- [x] **Step 3: Implement CSS for different status states (active, done, cached)**

### Task 2.2: Implement EventSource logic

- [x] **Step 1: Connect to /fetch_stream on form submission**
- [x] **Step 2: Handle 'tournaments' event to populate the initial list**
- [x] **Step 3: Handle progress updates to update the progress bar and list items**
- [x] **Step 4: Use index-based matching for robust list updates**
- [x] **Step 5: Implement auto-expansion of details and smooth scrolling**
- [x] **Step 6: Handle completion and trigger automatic download**

---

## Plan Completion Checklist

- [x] Backend streams real-time updates
- [x] Frontend displays overall progress bar
- [x] Frontend displays detailed tournament list with status icons
- [x] Cache status is visible in the UI
- [x] Details section is auto-expanded during progress
- [x] Automatic download is triggered upon completion
- [x] Connection is properly closed and errors are handled
