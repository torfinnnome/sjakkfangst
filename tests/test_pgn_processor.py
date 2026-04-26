"""Tests for the PGN processor module."""

from unittest.mock import Mock, patch

import pytest
from pgn_processor import download_broadcast_pgn, filter_games_by_fide, collect_opening_stats


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

class TestCollectOpeningStats:
    """Tests for collect_opening_stats function."""

    def test_empty_pgn_returns_empty_list(self):
        """Test that empty PGN returns empty list."""
        assert collect_opening_stats("", "1503014") == []
        assert collect_opening_stats(None, "1503014") == []

    def test_basic_stats_collection_as_white(self):
        """Test basic stats collection for player as White."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.02"]
[White "Carlsen"]
[Black "Opponent2"]
[Result "1/2-1/2"]
[WhiteFideId "1503014"]
[BlackFideId "3333333"]
[WhiteElo "2800"]
[BlackElo "2650"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1/2-1/2

[Event "Tournament"]
[Date "2024.03.03"]
[White "Carlsen"]
[Black "Opponent3"]
[Result "0-1"]
[WhiteFideId "1503014"]
[BlackFideId "4444444"]
[WhiteElo "2800"]
[BlackElo "2750"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 0-1
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        entry = stats[0]
        assert entry["opening"] == "Ruy Lopez: Berlin Defense"
        assert entry["eco"] == "C65"
        assert entry["games"] == 3
        assert entry["wins"] == 1
        assert entry["draws"] == 1
        assert entry["losses"] == 1
        assert entry["win_pct"] == 33
        assert entry["avg_elo"] == 2700
        assert entry["date_from"] == "2024.03.01"
        assert entry["date_to"] == "2024.03.03"

    def test_basic_stats_collection_as_black(self):
        """Test basic stats collection for player as Black."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Opponent"]
[Black "Carlsen"]
[Result "0-1"]
[WhiteFideId "2222222"]
[BlackFideId "1503014"]
[WhiteElo "2700"]
[BlackElo "2800"]
[Opening "Sicilian Defense"]
[ECO "B20"]

1. e4 c5 0-1
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        entry = stats[0]
        assert entry["opening"] == "Sicilian Defense"
        assert entry["wins"] == 1
        assert entry["losses"] == 0
        assert entry["avg_elo"] == 2700

    def test_eco_fallback_when_opening_missing(self):
        """Test that ECO lookup is used when Opening header is missing."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[ECO "A00"]

1. a3 a6 1-0
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        assert stats[0]["eco"] == "A00"
        assert "Amar" in stats[0]["opening"]

    def test_unknown_opening_when_no_headers(self):
        """Test that opening defaults to Unknown when no Opening/ECO headers."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]

1. e4 e5 1-0
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        assert stats[0]["opening"] == "Unknown"
        assert stats[0]["eco"] == ""

    def test_multiple_openings_grouped_separately(self):
        """Test that different openings are grouped separately."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.02"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "3333333"]
[WhiteElo "2800"]
[BlackElo "2600"]
[Opening "Queen's Gambit Declined"]
[ECO "D50"]

1. d4 d5 1-0
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 2
        # Sorted by games descending; both have 1 game, so order depends on insertion
        openings = {s["opening"] for s in stats}
        assert "Ruy Lopez: Berlin Defense" in openings
        assert "Queen's Gambit Declined: Been-Koomen Variation" in openings

    def test_sorted_by_game_count_descending(self):
        """Test that results are sorted by game count descending."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Lesser Opening"]
[ECO "A00"]

1. a3 a6 1-0

[Event "Tournament"]
[Date "2024.03.02"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "3333333"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Greater Opening"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.03"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "4444444"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Greater Opening"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.04"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "5555555"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Greater Opening"]
[ECO "C65"]

1. e4 e5 1-0
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 2
        assert stats[0]["opening"] == "Ruy Lopez: Berlin Defense"
        assert stats[0]["games"] == 3
        assert stats[1]["opening"] == "Amar Opening"
        assert stats[1]["games"] == 1

    def test_non_matching_games_ignored(self):
        """Test that games where player doesn't match FIDE ID are ignored."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "PlayerA"]
[Black "PlayerB"]
[Result "1-0"]
[WhiteFideId "1111111"]
[BlackFideId "2222222"]
[WhiteElo "2700"]
[BlackElo "2600"]
[Opening "Some Opening"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.02"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "3333333"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        assert stats[0]["opening"] == "Ruy Lopez: Berlin Defense"
        assert stats[0]["games"] == 1

    def test_draw_outcome_handling(self):
        """Test that draws are correctly counted."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1/2-1/2"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Berlin Defense"]
[ECO "C65"]

1. e4 e5 1/2-1/2

[Event "Tournament"]
[Date "2024.03.02"]
[White "Opponent"]
[Black "Carlsen"]
[Result "1/2-1/2"]
[WhiteFideId "2222222"]
[BlackFideId "1503014"]
[WhiteElo "2700"]
[BlackElo "2800"]
[Opening "Berlin Defense"]
[ECO "C65"]

1. e4 e5 1/2-1/2
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        assert stats[0]["draws"] == 2
        assert stats[0]["wins"] == 0
        assert stats[0]["losses"] == 0
        assert stats[0]["win_pct"] == 0

    def test_missing_elo_returns_none(self):
        """Test that missing Elo returns None for avg_elo."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[Opening "Unknown Opening"]
[ECO "A00"]

1. a3 a6 1-0
"""
        stats = collect_opening_stats(pgn_text, "1503014")

        assert len(stats) == 1
        assert stats[0]["avg_elo"] is None
