"""Tests for the PGN processor module."""

from unittest.mock import Mock, patch

import pytest
from pgn_processor import download_broadcast_pgn, filter_games_by_fide


class TestDownloadBroadcastPgn:
    """Tests for download_broadcast_pgn function."""

    @patch("pgn_processor.requests.get")
    def test_valid_broadcast_url_returns_pgn_text(self, mock_get):
        """Test that valid broadcast URL returns PGN text by extracting tournament ID."""
        # First call: fetch broadcast page
        mock_page_response = Mock()
        mock_page_response.status_code = 200
        mock_page_response.text = '<html><script id="page-init-data">{"relay":{"tour":{"id":"EdFRduLb"}}}</script></html>'
        
        # Second call: fetch PGN
        mock_pgn_response = Mock()
        mock_pgn_response.status_code = 200
        mock_pgn_response.text = """[Event "FIDE World Rapid Championship 2024"]
[White "Carlsen, Magnus"]
[Result "1-0"]

1. e4 e5 1-0"""
        
        mock_get.side_effect = [mock_page_response, mock_pgn_response]

        url = "https://lichess.org/broadcast/fide-world-rapid-blitz/round-13/05WiuPW4"
        result = download_broadcast_pgn(url)

        assert '[Event "FIDE World Rapid Championship 2024"]' in result
        # Check that it called the API with the ID found in JSON
        mock_get.assert_called_with(
            "https://lichess.org/api/broadcast/EdFRduLb.pgn", timeout=30
        )

    @patch("pgn_processor.requests.get")
    def test_http_error_returns_empty_string(self, mock_get):
        """Test that HTTP error returns empty string."""
        from requests import HTTPError

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        url = "https://lichess.org/broadcast/invalid/round/abc123"
        result = download_broadcast_pgn(url)

        assert result == ""

    @patch("pgn_processor.requests.get")
    def test_request_exception_returns_empty_string(self, mock_get):
        """Test that request exception returns empty string."""
        from requests import RequestException

        mock_get.side_effect = RequestException("Connection failed")

        url = "https://lichess.org/broadcast/tournament/round/abc123"
        result = download_broadcast_pgn(url)

        assert result == ""


class TestFilterGamesByFide:
    """Tests for filter_games_by_fide function."""

    def test_matching_white_fide_id_returns_game(self):
        """Test that PGN with matching WhiteFideId returns that game."""
        pgn_text = """[Event "FIDE World Rapid 2024"]
[Site "https://lichess.org/05WiuPW4"]
[White "Carlsen, Magnus"]
[Black "Nepomniachtchi, Ian"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "4168119"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
"""

        result = filter_games_by_fide(pgn_text, "1503014")

        assert '[WhiteFideId "1503014"]' in result
        assert "1. e4" in result

    def test_matching_black_fide_id_returns_game(self):
        """Test that PGN with matching BlackFideId returns that game."""
        pgn_text = """[Event "FIDE World Rapid 2024"]
[Site "https://lichess.org/05WiuPW4"]
[White "Carlsen, Magnus"]
[Black "Nepomniachtchi, Ian"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "4168119"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
"""

        result = filter_games_by_fide(pgn_text, "4168119")

        assert '[BlackFideId "4168119"]' in result
        assert "1. e4" in result

    def test_multiple_games_returns_only_matching(self):
        """Test that PGN with multiple games returns only matching games."""
        pgn_text = """[Event "Tournament A"]
[White "Player A"]
[Black "Player B"]
[Result "1-0"]
[WhiteFideId "1111111"]
[BlackFideId "2222222"]

1. e4 e5 2. Nf3 1-0

[Event "Tournament B"]
[White "Candidate"]
[Black "Opponent"]
[Result "0-1"]
[WhiteFideId "1503014"]
[BlackFideId "3333333"]

1. d4 d5 2. c4 0-1

[Event "Tournament C"]
[White "Another"]
[Black "Match"]
[Result "1/2-1/2"]
[WhiteFideId "4444444"]
[BlackFideId "1503014"]

1. Nf3 Nf6 1/2-1/2
"""

        result = filter_games_by_fide(pgn_text, "1503014")

        # Should have 2 games
        assert result.count("[Event ") == 2
        # Should contain both matching games
        assert '[Event "Tournament B"]' in result
        assert '[Event "Tournament C"]' in result
        # Should not contain non-matching game
        assert '[Event "Tournament A"]' not in result

    def test_no_matching_games_returns_empty_string(self):
        """Test that PGN with no matching FIDE ID returns empty string."""
        pgn_text = """[Event "Tournament"]
[White "Player"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1111111"]
[BlackFideId "2222222"]

1. e4 e5 1-0
"""

        result = filter_games_by_fide(pgn_text, "9999999")

        assert result == ""

    def test_malformed_pgn_handles_gracefully(self):
        """Test that malformed PGN games are handled gracefully."""
        pgn_text = """[Event "Good Game"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]

1. e4 e5 1-0

This is malformed content without proper headers
move1 move2 move3

[Event "Another Good Game"]
[White "Another"]
[Black "Player"]
[Result "0-1"]
[WhiteFideId "3333333"]
[BlackFideId "1503014"]

1. d4 d5 0-1
"""

        result = filter_games_by_fide(pgn_text, "1503014")

        # Should have 2 valid games
        assert result.count("[Event ") == 2
        assert '[Event "Good Game"]' in result
        assert '[Event "Another Good Game"]' in result
        # Malformed content should not cause crash
