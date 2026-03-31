"""Scraper module for fetching FIDE player data from Lichess."""

import re
from typing import Dict, List

import requests
from bs4 import BeautifulSoup


def parse_fide_url(url: str) -> Dict[str, str]:
    """Parse a Lichess FIDE player URL to extract FIDE ID and player name.

    Args:
        url: A URL in the format https://lichess.org/fide/{fide_id}/{player_name}

    Returns:
        Dict with 'fide_id' and 'player_name' keys.

    Raises:
        ValueError: If URL is invalid or doesn't match expected pattern.
    """
    # Remove protocol if present
    url = url.replace("https://", "").replace("http://", "")

    # Remove query parameters if present
    url = url.split("?")[0]

    # Remove trailing slash if present
    url = url.rstrip("/")

    # Use regex to match the FIDE URL pattern (case insensitive)
    pattern = r"^lichess\.org/fide/(\d+)/(\S+)$"
    match = re.match(pattern, url, re.IGNORECASE)

    if not match:
        raise ValueError(f"Invalid Lichess FIDE URL: {url}")

    fide_id = match.group(1)
    player_name = match.group(2)

    return {"fide_id": fide_id, "player_name": player_name}


def get_broadcasts(fide_id: str, player_name: str) -> List[Dict[str, str]]:
    """Fetch broadcast tournament data from a Lichess FIDE player page.

    Args:
        fide_id: The FIDE ID of the player (e.g., "1503014")
        player_name: The player name slug (e.g., "Carlsen_Magnus")

    Returns:
        List of dicts with 'url' and 'name' for each broadcast tournament.
    """
    url = f"https://lichess.org/fide/{fide_id}/{player_name}"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    relay_cards = soup.find(class_="relay-cards")
    if not relay_cards:
        return []

    broadcasts = []
    for link in relay_cards.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/broadcast/"):
            # Get the tournament name from the h3 with class 'relay-card__title'
            name_elem = link.find("h3", class_="relay-card__title")
            name = name_elem.get_text(strip=True) if name_elem else "Unknown Tournament"
            
            broadcasts.append({
                "url": f"https://lichess.org{href}",
                "name": name
            })

    return broadcasts
