"""Scraper module for fetching FIDE player data from Lichess."""

import os
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

RETRY_ATTEMPTS = int(os.environ.get("RETRY_ATTEMPTS", "3"))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "2"))


def _fetch_with_retry(url: str, timeout: int = 30) -> requests.Response:
    """Fetch a URL with retry logic for transient errors."""
    last_exception = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exception = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    raise last_exception

# Maximum number of broadcasts to fetch per player (configurable via env var)
MAX_BROADCASTS = int(os.environ.get("MAX_BROADCASTS", "100"))


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


def _parse_page_broadcasts(soup) -> List[Dict[str, str]]:
    """Extract broadcasts from a parsed page and check for next page link."""
    relay_cards = soup.find(class_="relay-cards")
    if not relay_cards:
        return [], None

    broadcasts = []
    for link in relay_cards.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/broadcast/"):
            name_elem = link.find("h3", class_="relay-card__title")
            name = name_elem.get_text(strip=True) if name_elem else "Unknown Tournament"

            broadcasts.append({
                "url": f"https://lichess.org{href}",
                "name": name
            })

    # Check for next page link
    pager = soup.find("div", class_="pager")
    next_url = None
    if pager:
        next_link = pager.find("a", rel="next", href=True)
        if next_link:
            next_url = next_link["href"]

    return broadcasts, next_url


def get_broadcasts(
    fide_id: str,
    player_name: str,
    max_broadcasts: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Fetch broadcast tournament data from a Lichess FIDE player page.

    Fetches broadcasts across multiple pages, respecting pagination. The
    number of broadcasts is capped to avoid excessive requests.

    Args:
        fide_id: The FIDE ID of the player (e.g., "1503014")
        player_name: The player name slug (e.g., "Carlsen_Magnus")
        max_broadcasts: Maximum number of broadcasts to fetch. Defaults to
            MAX_BROADCASTS (configurable via MAX_BROADCASTS env var, default 100).

    Returns:
        List of dicts with 'url' and 'name' for each broadcast tournament,
        deduplicated by URL.
    """
    if max_broadcasts is None:
        max_broadcasts = MAX_BROADCASTS

    url = f"https://lichess.org/fide/{fide_id}/{player_name}"
    seen_urls = set()
    broadcasts = []

    try:
        response = _fetch_with_retry(url, timeout=30)
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    page_broadcasts, next_url = _parse_page_broadcasts(soup)

    for bc in page_broadcasts:
        if bc["url"] not in seen_urls:
            seen_urls.add(bc["url"])
            broadcasts.append(bc)

    # Follow pagination until we've hit the limit or there are no more pages
    while next_url and len(broadcasts) < max_broadcasts:
        full_next_url = f"https://lichess.org{next_url}"

        try:
            response = _fetch_with_retry(full_next_url, timeout=30)
        except requests.RequestException:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        page_broadcasts, next_url = _parse_page_broadcasts(soup)

        for bc in page_broadcasts:
            if bc["url"] not in seen_urls:
                seen_urls.add(bc["url"])
                broadcasts.append(bc)

        if len(broadcasts) >= max_broadcasts:
            break

        time.sleep(1)

    return broadcasts[:max_broadcasts]
