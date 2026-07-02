"""Tests for collect_opponent_stats function."""

import pytest

from pgn_processor import collect_opponent_stats


class TestCollectOpponentStats:
    """Tests for collect_opponent_stats function."""

    def test_empty_pgn_returns_empty(self):
        """Test that empty string and None both return empty result."""
        assert collect_opponent_stats("", "1503014") == {"stats": [], "player_name": ""}
        assert collect_opponent_stats(None, "1503014") == {"stats": [], "player_name": ""}

    def test_basic_stats_as_white(self):
        """Test basic stats collection for player as White against multiple opponents."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Nepomniachtchi"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2093362"]
[WhiteElo "2800"]
[BlackElo "2780"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.02"]
[White "Carlsen"]
[Black "Nepomniachtchi"]
[Result "1/2-1/2"]
[WhiteFideId "1503014"]
[BlackFideId "2093362"]
[WhiteElo "2800"]
[BlackElo "2790"]
[Opening "Sicilian Defense"]
[ECO "B90"]

1. e4 c5 1/2-1/2

[Event "Tournament"]
[Date "2024.03.03"]
[White "Carlsen"]
[Black "Ding"]
[Result "0-1"]
[WhiteFideId "1503014"]
[BlackFideId "1037965"]
[WhiteElo "2800"]
[BlackElo "2770"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 0-1
"""
        result = collect_opponent_stats(pgn_text, "1503014")
        stats = result["stats"]

        assert len(stats) == 2

        nepo = [s for s in stats if s["opponent"] == "Nepomniachtchi"][0]
        assert nepo["opponent_fide_id"] == "2093362"
        assert nepo["games"] == 2
        assert nepo["wins"] == 1
        assert nepo["draws"] == 1
        assert nepo["losses"] == 0
        assert nepo["win_pct"] == 50
        assert nepo["avg_elo"] == 2785
        assert nepo["date_from"] == "2024.03.01"
        assert nepo["date_to"] == "2024.03.02"
        assert len(nepo["top_openings"]) == 2
        assert nepo["top_openings"][0]["opening"] == "Ruy Lopez"
        assert nepo["top_openings"][0]["games"] == 1
        assert nepo["top_openings"][1]["opening"] == "Sicilian Defense"
        assert nepo["top_openings"][1]["games"] == 1

        ding = [s for s in stats if s["opponent"] == "Ding"][0]
        assert ding["games"] == 1
        assert ding["wins"] == 0
        assert ding["draws"] == 0
        assert ding["losses"] == 1
        assert ding["win_pct"] == 0
        assert ding["avg_elo"] == 2770

    def test_basic_stats_as_black(self):
        """Test basic stats collection for player as Black with outcome flipping."""
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
        result = collect_opponent_stats(pgn_text, "1503014")
        stats = result["stats"]

        assert len(stats) == 1
        entry = stats[0]
        assert entry["opponent"] == "Opponent"
        assert entry["wins"] == 1
        assert entry["losses"] == 0
        assert entry["avg_elo"] == 2700

    def test_sorted_by_games_descending(self):
        """Test that opponents with more games appear first."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "RareOpponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "1111111"]
[WhiteElo "2800"]
[BlackElo "2600"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.02"]
[White "Carlsen"]
[Black "FrequentOpponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.03"]
[White "Carlsen"]
[Black "FrequentOpponent"]
[Result "1/2-1/2"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Sicilian Defense"]
[ECO "B90"]

1. e4 c5 1/2-1/2

[Event "Tournament"]
[Date "2024.03.04"]
[White "Carlsen"]
[Black "FrequentOpponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0
"""
        result = collect_opponent_stats(pgn_text, "1503014")
        stats = result["stats"]

        assert len(stats) == 2
        assert stats[0]["opponent"] == "FrequentOpponent"
        assert stats[0]["games"] == 3
        assert stats[1]["opponent"] == "RareOpponent"
        assert stats[1]["games"] == 1

    def test_opponent_fide_id_collected(self):
        """Test that opponent FIDE ID is captured in result."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "Anand"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "50000"]
[WhiteElo "2800"]
[BlackElo "2750"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0
"""
        result = collect_opponent_stats(pgn_text, "1503014")
        stats = result["stats"]

        assert len(stats) == 1
        assert stats[0]["opponent_fide_id"] == "50000"

    def test_missing_elo_handled(self):
        """Test that empty Elo string results in avg_elo of None."""
        pgn_text = """[Event "Tournament"]
[Date "2024.03.01"]
[White "Carlsen"]
[Black "UnknownPlayer"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "9999999"]
[Opening "Unknown Opening"]
[ECO "A00"]

1. a3 a6 1-0
"""
        result = collect_opponent_stats(pgn_text, "1503014")
        stats = result["stats"]

        assert len(stats) == 1
        assert stats[0]["avg_elo"] is None

    def test_top_openings_sorted_by_games(self):
        """Test that top_openings list is sorted by games descending."""
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
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1-0

[Event "Tournament"]
[Date "2024.03.03"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1/2-1/2"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Ruy Lopez"]
[ECO "C65"]

1. e4 e5 1/2-1/2

[Event "Tournament"]
[Date "2024.03.04"]
[White "Carlsen"]
[Black "Opponent"]
[Result "1-0"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "Sicilian Defense"]
[ECO "B90"]

1. e4 c5 1-0

[Event "Tournament"]
[Date "2024.03.05"]
[White "Carlsen"]
[Black "Opponent"]
[Result "0-1"]
[WhiteFideId "1503014"]
[BlackFideId "2222222"]
[WhiteElo "2800"]
[BlackElo "2700"]
[Opening "French Defense"]
[ECO "C00"]

1. e4 e6 0-1
"""
        result = collect_opponent_stats(pgn_text, "1503014")
        stats = result["stats"]

        assert len(stats) == 1
        entry = stats[0]
        assert entry["top_openings"][0]["opening"] == "Ruy Lopez"
        assert entry["top_openings"][0]["games"] == 3
        assert entry["top_openings"][1]["opening"] == "Sicilian Defense"
        assert entry["top_openings"][1]["games"] == 1
        assert entry["top_openings"][2]["opening"] == "French Defense"
        assert entry["top_openings"][2]["games"] == 1
