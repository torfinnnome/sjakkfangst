# Sjakkfangst

**Sjakkfangst** is a Flask web application to fetch chess games for FIDE players from Lichess broadcasts.

## Installation

```bash
uv pip install -r requirements.txt
```

## Usage

1. Run the Flask application:
```bash
python app.py
```

2. Open your browser to `http://localhost:5000`

3. Enter a Lichess FIDE player URL in the format:
   `https://lichess.org/fide/{fide_id}/{player_name}`
   Example: `https://lichess.org/fide/1503014/Carlsen_Magnus`

4. The app will download all broadcast games for that player and return a downloadable PGN file.

## Project Structure

- `app.py` - Flask web application entry point
- `scraper.py` - URL parsing and broadcast fetching
- `pgn_processor.py` - PGN download and filtering
- `templates/index.html` - Web interface
- `tests/` - Unit tests

## Testing

Run tests with:
```bash
python -m pytest tests/ -v
```

## Requirements

- Python 3.8+
- See `requirements.txt` for dependencies
