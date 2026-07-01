"""Flask web application for fetching FIDE player games from Lichess broadcasts."""

import io
import json
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, send_file, Response, render_template

from scraper import parse_fide_url, get_broadcasts
from pgn_processor import (
    download_broadcast_pgn,
    filter_and_collect_stats,
    filter_games_by_fide,  # kept for test mocking compatibility
    collect_opening_stats,
    _merge_raw_stats,
    _format_raw_stats,
)
from cache import (
    get_cached_player, cache_player, get_cached_tournament, cache_tournament,
    _get_hash, _get_metadata_path, cache_task, get_cached_task,
)
from rate_limit import rate_limiter

url_logger = logging.getLogger("sjakkfangst.urls")
url_logger.propagate = False

app = Flask(__name__)

# Security headers applied to every response. CSP denies inline scripts/styles
# (static files are served from /static) and all external origins.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.after_request
def set_security_headers(response):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response

# Parallel download configuration (env-configurable)
DOWNLOAD_WORKERS = int(os.environ.get("DOWNLOAD_WORKERS", "3"))
LICHESS_MIN_SPACING = float(os.environ.get("LICHESS_MIN_SPACING", "2"))
SSE_MAX_DURATION = int(os.environ.get("SSE_MAX_DURATION", "600"))  # seconds (P12)

# Shared rate limiter so concurrent download workers stay polite to Lichess.
_lichess_lock = threading.Lock()
_lichess_last_request = 0.0


def _rate_limited_download(broadcast_url: str) -> str:
    """Download a broadcast PGN, spacing out Lichess requests across workers."""
    global _lichess_last_request
    with _lichess_lock:
        now = time.time()
        wait = LICHESS_MIN_SPACING - (now - _lichess_last_request)
        if wait < 0:
            wait = 0
        _lichess_last_request = now + wait
    if wait > 0:
        time.sleep(wait)
    return download_broadcast_pgn(broadcast_url)


def _is_same_origin(header_value: str) -> bool:
    """Check whether an Origin/Referer header matches this server's origin."""
    if not header_value:
        return False
    host = request.host
    return (
        header_value == f"http://{host}"
        or header_value == f"https://{host}"
        or header_value.startswith(f"http://{host}/")
        or header_value.startswith(f"https://{host}/")
    )


@app.route("/", methods=["GET"])
def index():
    """Render the main form for entering FIDE player URL."""
    return render_template("index.html")


@app.route("/fetch_stream", methods=["GET"])
def fetch_stream():
    """Stream progress of PGN fetching as Server-Sent Events."""
    # Block cross-site requests (CSRF): /fetch_stream triggers scraping and
    # disk writes, so require same-origin Origin or Referer (S6).
    origin = request.headers.get("Origin") or ""
    referer = request.headers.get("Referer") or ""
    if not _is_same_origin(origin) and not _is_same_origin(referer):
        return "Forbidden: cross-site requests not allowed", 403

    client_ip = request.remote_addr
    allowed, reason, wait = rate_limiter.check(client_ip)
    if not allowed:
        return Response(
            f"data: {json.dumps({'rate_limit': reason, 'wait': int(wait) + 1})}\n\n",
            mimetype="text/event-stream",
        )

    url = request.args.get("url", "").strip()
    if not url:
        return "Error: Please provide a URL", 400

    try:
        player_info = parse_fide_url(url)
    except ValueError:
        return "Error: Invalid FIDE URL", 400

    fide_id = player_info["fide_id"]
    player_name = player_info["player_name"]

    def generate():
        start_time = time.time()  # P12: max-duration guard

        # Get list of broadcasts
        broadcasts = get_broadcasts(fide_id, player_name)

        if not broadcasts:
            yield f"data: {json.dumps({'error': 'No broadcasts found'})}\n\n"
            return

        all_games = []
        all_raw_stats = []
        all_player_names = []
        p_hits = 0
        t_hits = 0
        d_hits = 0

        # Deduplicate broadcasts by tournament slug
        unique_broadcasts = []
        seen_slugs = set()
        for b in broadcasts:
            # Extract tournament slug
            parts = b["url"].split("/")
            if len(parts) < 5:
                continue
            slug = parts[4]
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                unique_broadcasts.append(b)

        total = len(unique_broadcasts)

        # Build player game link hash from FIDE ID
        player_hash = f"#players/{fide_id}"

        # Send list of all tournaments (name + url) to the client
        tournament_list = [{"name": b["name"], "url": b["url"]} for b in unique_broadcasts]
        yield f"data: {json.dumps({'tournaments': tournament_list, 'player_hash': player_hash})}\n\n"

        completed = 0
        to_download = []  # (index, broadcast, tournament_id) needing a network fetch

        # First pass: serve cache hits immediately (in order), queue misses.
        for i, broadcast in enumerate(unique_broadcasts):
            name = broadcast["name"]
            url_parts = broadcast["url"].rstrip("/").split("/")
            tournament_id = url_parts[-1] if len(url_parts) >= 5 else ""

            player_cached = get_cached_player(fide_id, tournament_id)
            tournament_pgn = None
            if player_cached is None:
                tournament_pgn = get_cached_tournament(tournament_id)

            if player_cached:
                completed += 1
                progress = max(1, int((completed / total) * 100)) if total else 100
                yield f"data: {json.dumps({'index': i, 'progress': progress, 'name': name, 'cached': True, 'url': broadcast['url']})}\n\n"
                p_hits += 1
                all_games.append(player_cached)
                continue

            if tournament_pgn:
                completed += 1
                progress = max(1, int((completed / total) * 100)) if total else 100
                yield f"data: {json.dumps({'index': i, 'progress': progress, 'name': name, 'cached': True, 'url': broadcast['url']})}\n\n"
                # Read tournament status from cache metadata to propagate to player cache
                hash_key = _get_hash(tournament_id)
                meta_path = _get_metadata_path("tournaments", hash_key)
                tournament_status = None
                try:
                    meta_data = json.loads(meta_path.read_text())
                    tournament_status = meta_data.get("status")
                except Exception:
                    pass
                res = filter_and_collect_stats(tournament_pgn, fide_id, player_name)
                if res["filtered_pgn"]:
                    cache_player(fide_id, tournament_id, res["filtered_pgn"], tournament_status)
                    t_hits += 1
                    all_games.append(res["filtered_pgn"])
                    all_raw_stats.append(res["stats"])
                    if res["player_name"]:
                        all_player_names.append(res["player_name"])
                continue

            # Not cached — queue for parallel download
            to_download.append((i, broadcast, tournament_id))

        # Second pass: download the uncached tournaments concurrently, with a
        # shared rate limiter so we stay polite to Lichess. Events are emitted
        # as downloads complete (out of order); the client keys off `index`.
        if to_download:
            with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
                future_to_info = {
                    executor.submit(_rate_limited_download, b["url"]): (i, b, tid)
                    for (i, b, tid) in to_download
                }
                for future in as_completed(future_to_info):
                    # P12: abort if SSE stream exceeds max duration
                    if time.time() - start_time > SSE_MAX_DURATION:
                        yield f"data: {json.dumps({'error': 'Request timed out — too many broadcasts'})}\n\n"
                        return
                    i, broadcast, tournament_id = future_to_info[future]
                    name = broadcast["name"]
                    try:
                        pgn_text = future.result()
                    except Exception:
                        pgn_text = ""
                    if pgn_text:
                        cache_tournament(tournament_id, pgn_text, broadcast["url"])
                        res = filter_and_collect_stats(pgn_text, fide_id, player_name)
                        if res["filtered_pgn"]:
                            cache_player(fide_id, tournament_id, res["filtered_pgn"])
                            d_hits += 1
                            all_games.append(res["filtered_pgn"])
                            all_raw_stats.append(res["stats"])
                            if res["player_name"]:
                                all_player_names.append(res["player_name"])
                    completed += 1
                    progress = max(1, int((completed / total) * 100)) if total else 100
                    yield f"data: {json.dumps({'index': i, 'progress': progress, 'name': name, 'cached': False, 'url': broadcast['url']})}\n\n"

        if not all_games:
            yield f"data: {json.dumps({'error': 'No matching games found'})}\n\n"
            return

        # Success! Store result and notify client
        task_id = str(uuid.uuid4())
        combined_pgn = "\n\n".join(all_games)
        filename = f"{player_name}_fide_games_sjakkfangst.pgn"
        cache_task(task_id, combined_pgn, filename)

        # Collect opening stats for the player
        merged = _merge_raw_stats(all_raw_stats)
        final_stats = _format_raw_stats(merged)
        player_name_resolved = all_player_names[0] if all_player_names else ""
        if not player_name_resolved:
            opening_result = collect_opening_stats(combined_pgn, fide_id)
            player_name_resolved = opening_result.get("player_name", "")

        url_logger.info("%s  %s (%s)  %s tours  p=%s t=%s d=%s  = %s games",
                        url, player_name, fide_id, total, p_hits, t_hits, d_hits, len(all_games))
        yield f"data: {json.dumps({'progress': 100, 'done': True, 'id': task_id, 'stats': final_stats, 'player_name': player_name_resolved})}\n\n"

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Accel-Buffering"] = "no"  # Disable buffering for Nginx/proxies
    return response


@app.route("/download/<task_id>")
def download(task_id):
    """Download the final PGN file for a completed task."""
    task = get_cached_task(task_id)
    if not task:
        return "Task not found or expired", 404

    return send_file(
        io.BytesIO(task["pgn"].encode("utf-8")),
        mimetype="application/x-chess-pgn",
        as_attachment=True,
        download_name=task["filename"],
    )


if os.environ.get("SJAKKFANGST_LOG_URLS"):
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    url_logger.addHandler(_h)
    url_logger.setLevel(logging.INFO)

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
