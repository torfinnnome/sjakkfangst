"""Flask web application for fetching FIDE player games from Lichess broadcasts."""

import io
import json
import logging
import os
import sys
import time
import uuid
from flask import Flask, request, send_file, Response, render_template

from scraper import parse_fide_url, get_broadcasts
from pgn_processor import download_broadcast_pgn, filter_games_by_fide, collect_opening_stats
from cache import get_cached_player, cache_player, get_cached_tournament, cache_tournament, _get_hash, _get_metadata_path
from rate_limit import rate_limiter

url_logger = logging.getLogger("sjakkfangst.urls")
url_logger.propagate = False

app = Flask(__name__)

# Simple in-memory cache for task results
# In a production app, this would be a database or Redis
tasks = {}


@app.route("/", methods=["GET"])
def index():
    """Render the main form for entering FIDE player URL."""
    return render_template("index.html")


@app.route("/fetch_stream", methods=["GET"])
def fetch_stream():
    """Stream progress of PGN fetching as Server-Sent Events."""
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

    url_logger.info("URL: %s  fide: %s  name: %s", url, fide_id, player_name)

    def generate():
        # Get list of broadcasts
        broadcasts = get_broadcasts(fide_id, player_name)

        if not broadcasts:
            yield f"data: {json.dumps({'error': 'No broadcasts found'})}\n\n"
            return

        all_games = []
        processed_tournaments = set()

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

        # Send list of all tournament names to the client
        tournament_names = [b["name"] for b in unique_broadcasts]
        yield f"data: {json.dumps({'tournaments': tournament_names})}\n\n"

        for i, broadcast in enumerate(unique_broadcasts):
            name = broadcast["name"]
            # Calculate progress: show at least 1% if we have tournaments
            progress = int((i / total) * 100)
            if progress == 0 and total > 0:
                progress = 1

            # Extract tournament_id from URL
            url_parts = broadcast["url"].rstrip("/").split("/")
            tournament_id = url_parts[-1] if len(url_parts) >= 5 else ""

            # Check caches
            player_cached = get_cached_player(fide_id, tournament_id)
            is_cached = player_cached is not None

            tournament_pgn = None
            if not is_cached:
                tournament_pgn = get_cached_tournament(tournament_id)
                is_cached = tournament_pgn is not None

            # Send progress update with cached info
            yield f"data: {json.dumps({'index': i, 'progress': progress, 'name': name, 'cached': is_cached})}\n\n"

            if player_cached:
                if player_cached:
                    url_logger.info("[%s/%s] %s - player cache hit", i + 1, total, name)
                    all_games.append(player_cached)
                continue

            if tournament_pgn:
                # Read tournament status from cache metadata to propagate to player cache
                hash_key = _get_hash(tournament_id)
                meta_path = _get_metadata_path("tournaments", hash_key)
                tournament_status = None
                try:
                    meta_data = json.loads(meta_path.read_text())
                    tournament_status = meta_data.get("status")
                except Exception:
                    pass

                filtered = filter_games_by_fide(tournament_pgn, fide_id, player_name)
                if filtered:
                    cache_player(fide_id, tournament_id, filtered, tournament_status)
                    url_logger.info("[%s/%s] %s - tournament cache hit", i + 1, total, name)
                    all_games.append(filtered)
                continue

            # Respect Lichess rate limits (only if actually downloading)
            if i > 0:
                time.sleep(3)

            pgn_text = download_broadcast_pgn(broadcast["url"])
            if pgn_text:
                # Cache full tournament PGN
                cache_tournament(tournament_id, pgn_text, broadcast["url"])
                # Pass player_name as fallback for filtering
                filtered = filter_games_by_fide(pgn_text, fide_id, player_name)
                cache_player(fide_id, tournament_id, filtered)
                if filtered:
                    url_logger.info("[%s/%s] %s - downloaded", i + 1, total, name)
                    all_games.append(filtered)

        if not all_games:
            url_logger.info("no games found for %s", player_name)
            yield f"data: {json.dumps({'error': 'No matching games found'})}\n\n"
            return

        # Success! Store result and notify client
        task_id = str(uuid.uuid4())
        combined_pgn = "\n\n".join(all_games)
        tasks[task_id] = {
            "pgn": combined_pgn,
            "filename": f"{player_name}_fide_games_sjakkfangst.pgn",
        }

        # Collect opening stats for the player
        opening_stats = collect_opening_stats(combined_pgn, fide_id)

        url_logger.info("done: %s — %s games", player_name, len(all_games))
        yield f"data: {json.dumps({'progress': 100, 'done': True, 'id': task_id, 'stats': opening_stats})}\n\n"

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Accel-Buffering"] = "no"  # Disable buffering for Nginx/proxies
    return response


@app.route("/download/<task_id>")
def download(task_id):
    """Download the final PGN file for a completed task."""
    task = tasks.get(task_id)
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
