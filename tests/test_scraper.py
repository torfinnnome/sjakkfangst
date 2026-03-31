"""Tests for the scraper module."""

from unittest.mock import Mock, patch

import pytest
from scraper import get_broadcasts, parse_fide_url


def test_parse_fide_url_valid():
    """Test parsing a valid Lichess FIDE URL."""
    url = "https://lichess.org/fide/1503014/Carlsen_Magnus"
    result = parse_fide_url(url)
    assert result == {"fide_id": "1503014", "player_name": "Carlsen_Magnus"}


def test_parse_fide_url_no_protocol():
    """Test parsing URL without protocol."""
    url = "lichess.org/fide/1503014/Carlsen_Magnus"
    result = parse_fide_url(url)
    assert result == {"fide_id": "1503014", "player_name": "Carlsen_Magnus"}


def test_parse_fide_url_with_query_params():
    """Test parsing URL with query parameters (should be ignored)."""
    url = "https://lichess.org/fide/1503014/Carlsen_Magnus?foo=bar"
    result = parse_fide_url(url)
    assert result == {"fide_id": "1503014", "player_name": "Carlsen_Magnus"}


def test_parse_fide_url_invalid_raises_error():
    """Test that invalid URL raises ValueError."""
    with pytest.raises(ValueError):
        parse_fide_url("https://example.com/fide/1503014/Carlsen")


def test_parse_fide_url_missing_path_raises_error():
    """Test URL without FIDE path raises ValueError."""
    with pytest.raises(ValueError):
        parse_fide_url("https://lichess.org/notfide/1503014")


def test_parse_fide_url_incomplete_path_raises_error():
    """Test URL with incomplete path raises ValueError."""
    with pytest.raises(ValueError):
        parse_fide_url("https://lichess.org/fide/1503014")


def test_parse_fide_url_uppercase():
    """Test parsing URL with uppercase letters in domain."""
    url = "https://Lichess.org/fide/1503014/Carlsen_Magnus"
    result = parse_fide_url(url)
    assert result == {"fide_id": "1503014", "player_name": "Carlsen_Magnus"}


def test_parse_fide_url_trailing_slash():
    """Test parsing URL with trailing slash."""
    url = "https://lichess.org/fide/1503014/Carlsen_Magnus/"
    result = parse_fide_url(url)
    assert result == {"fide_id": "1503014", "player_name": "Carlsen_Magnus"}


def test_parse_fide_url_uppercase_and_trailing_slash():
    """Test parsing URL with uppercase domain and trailing slash."""
    url = "https://LICHESS.org/fide/1503014/Carlsen_Magnus/"
    result = parse_fide_url(url)
    assert result == {"fide_id": "1503014", "player_name": "Carlsen_Magnus"}


class TestGetBroadcasts:
    """Tests for get_broadcasts function."""

    @patch("scraper.requests.get")
    def test_valid_fide_id_returns_broadcast_urls(self, mock_get):
        """Test that valid FIDE ID returns list of broadcast URLs."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <body>
            <div class="relay-cards">
                <a href="/broadcast/tata-steel-2024/round-1/abc123">Round 1</a>
                <a href="/broadcast/tata-steel-2024/round-2/def456">Round 2</a>
            </div>
        </body>
        </html>
        """
        mock_get.return_value = mock_response

        result = get_broadcasts("1503014", "Carlsen_Magnus")

        assert result == [
            "https://lichess.org/broadcast/tata-steel-2024/round-1/abc123",
            "https://lichess.org/broadcast/tata-steel-2024/round-2/def456",
        ]
        mock_get.assert_called_once_with(
            "https://lichess.org/fide/1503014/Carlsen_Magnus", timeout=30
        )

    @patch("scraper.requests.get")
    def test_section_tag_returns_broadcast_urls(self, mock_get):
        """Test that relay-cards in a section tag also works."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <body>
            <section class="relay-cards">
                <a href="/broadcast/norwegian-championship-2025/round-1/xyz">Round 1</a>
            </section>
        </body>
        </html>
        """
        mock_get.return_value = mock_response

        result = get_broadcasts("1503014", "Carlsen_Magnus")

        assert result == [
            "https://lichess.org/broadcast/norwegian-championship-2025/round-1/xyz"
        ]

    @patch("scraper.requests.get")
    def test_no_broadcasts_returns_empty_list(self, mock_get):
        """Test that HTML with no broadcasts returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <body>
            <div class="relay-cards">
            </div>
        </body>
        </html>
        """
        mock_get.return_value = mock_response

        result = get_broadcasts("1503014", "Carlsen_Magnus")

        assert result == []

    @patch("scraper.requests.get")
    def test_no_relay_cards_section_returns_empty_list(self, mock_get):
        """Test that HTML without relay-cards section returns empty list."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        <html>
        <body>
            <div>Some content</div>
        </body>
        </html>
        """
        mock_get.return_value = mock_response

        result = get_broadcasts("1503014", "Carlsen_Magnus")

        assert result == []

    @patch("scraper.requests.get")
    def test_http_error_returns_empty_list(self, mock_get):
        """Test that HTTP errors are handled gracefully with empty list."""
        from requests import HTTPError

        mock_get.side_effect = HTTPError("404 Not Found")

        result = get_broadcasts("1503014", "Carlsen_Magnus")

        assert result == []

    @patch("scraper.requests.get")
    def test_request_exception_returns_empty_list(self, mock_get):
        """Test that request exceptions are handled gracefully."""
        from requests import RequestException

        mock_get.side_effect = RequestException("Connection failed")

        result = get_broadcasts("1503014", "Carlsen_Magnus")

        assert result == []
