"""Flask web application for fetching FIDE player games from Lichess broadcasts."""

import io
import json
import time
import uuid
from flask import Flask, render_template, request, send_file, Response

from scraper import parse_fide_url, get_broadcasts
from pgn_processor import download_broadcast_pgn, filter_games_by_fide

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
    url = request.args.get("url", "").strip()
    if not url:
        return "Error: Please provide a URL", 400

    try:
        player_info = parse_fide_url(url)
    except ValueError as e:
        return f"Error: {e}", 400

    fide_id = player_info["fide_id"]
    player_name = player_info["player_name"]

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
            parts = b['url'].split("/")
            if len(parts) < 5:
                continue
            slug = parts[4]
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                unique_broadcasts.append(b)

        total = len(unique_broadcasts)

        for i, broadcast in enumerate(unique_broadcasts):
            name = broadcast['name']
            # Calculate progress: show at least 1% if we have tournaments
            progress = int((i / total) * 100)
            if progress == 0 and total > 0:
                progress = 1
            
            # Send progress update
            yield f"data: {json.dumps({'progress': progress, 'name': name})}\n\n"

            # Respect Lichess rate limits (3 second delay between tournament requests)
            if i > 0:
                time.sleep(3)

            pgn_text = download_broadcast_pgn(broadcast['url'])
            if pgn_text:
                # Pass player_name as fallback for filtering
                filtered = filter_games_by_fide(pgn_text, fide_id, player_name)
                if filtered:
                    all_games.append(filtered)

        if not all_games:
            yield f"data: {json.dumps({'error': 'No matching games found'})}\n\n"
            return

        # Success! Store result and notify client
        task_id = str(uuid.uuid4())
        combined_pgn = "\n\n".join(all_games)
        tasks[task_id] = {
            "pgn": combined_pgn,
            "filename": f"{player_name}_fide_games.pgn"
        }

        yield f"data: {json.dumps({'progress': 100, 'done': True, 'id': task_id})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


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


if __name__ == "__main__":
    app.run(debug=True)
