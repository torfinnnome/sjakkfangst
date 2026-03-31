"""PGN processor module for downloading PGN files from broadcasts."""

import io
import re

import chess.pgn
import requests


def download_broadcast_pgn(broadcast_url: str) -> str:
    """Download PGN data from a Lichess broadcast URL.

    Args:
        broadcast_url: A URL in the format https://lichess.org/broadcast/tournament-slug/round-slug/id
                       or https://lichess.org/broadcast/tournament-slug/id

    Returns:
        Raw PGN text from the broadcast, or empty string on error.
    """
    try:
        # Fetch the broadcast page to find the actual tournament ID in the JSON data
        page_response = requests.get(broadcast_url, timeout=30)
        page_response.raise_for_status()

        # The tournament ID is inside the page-init-data JSON in the HTML
        # Look for "tour":{"id":"XXXXXX"
        match = re.search(r'"tour":\{"id":"([^"]+)"', page_response.text)
        if match:
            tournament_id = match.group(1)
        else:
            # Fallback: find the first 8-char ID in the URL path
            # e.g., /broadcast/tournament-name/round-name/ROUNDID
            url_parts = broadcast_url.rstrip("/").split("/")
            tournament_id = url_parts[-1]

        # Construct API URL using the tournament ID
        api_url = f"https://lichess.org/api/broadcast/{tournament_id}.pgn"

        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return ""


def filter_games_by_fide(pgn_text: str, fide_id: str, player_name: str = "") -> str:
    """Filter PGN games by FIDE ID or player name.

    Args:
        pgn_text: Raw PGN text containing one or more games.
        fide_id: FIDE ID to filter for (as string).
        player_name: Optional player name slug (e.g. "Carlsen_Magnus") for fallback.

    Returns:
        Filtered PGN text containing matching games.
    """
    if not pgn_text:
        return ""

    matching_games = []
    pgn_stream = io.StringIO(pgn_text)
    
    # Prepare player name variations for matching
    name_variants = []
    if player_name:
        name_variants.append(player_name.lower())
        name_variants.append(player_name.replace("_", " ").lower())
        # Try "Lastname, Firstname" format if slug is "Lastname_Firstname"
        if "_" in player_name:
            parts = player_name.split("_")
            name_variants.append(f"{parts[0]}, {parts[1]}".lower())

    while True:
        try:
            game = chess.pgn.read_game(pgn_stream)
            if game is None:
                break

            # 1. Check FIDE IDs from headers (priority)
            white_fide = game.headers.get("WhiteFideId", "")
            black_fide = game.headers.get("BlackFideId", "")

            is_match = (white_fide == fide_id or black_fide == fide_id)

            # 2. Fallback: Check player names if no FIDE ID match
            if not is_match and name_variants:
                white_name = game.headers.get("White", "").lower()
                black_name = game.headers.get("Black", "").lower()
                
                for variant in name_variants:
                    if variant in white_name or variant in black_name:
                        is_match = True
                        break

            if is_match:
                # Export the matching game to PGN string
                exporter = chess.pgn.StringExporter()
                matching_games.append(game.accept(exporter))
        except Exception:
            continue

    return "\n\n".join(matching_games)
