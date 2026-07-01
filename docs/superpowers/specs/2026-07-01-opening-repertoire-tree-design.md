# F3: Opening Repertoire Tree — Design Spec

## Overview
Extend the opening stats table with an expandable move tree per opening. Each tree shows how the player's games diverge move-by-move, revealing their most common continuations and win rates at each ply.

## Configuration
| Constant | Value | Description |
|----------|-------|-------------|
| `TREE_DEPTH` | 6 | Max plies (half-moves) from the opening root |
| `TREE_TOP_N` | 5 | Number of top moves shown per level; rest collapse |

Both are module-level constants in `pgn_processor.py`, easily adjustable.

## Backend

### Data Model
New function `build_opening_tree(pgn_text, fide_id)` returns a list of opening entries, each with a nested `tree` structure appended to the existing stats:

```python
{
    "opening": "Ruy Lopez",
    "eco": "C65",
    "games": 42,
    "wins": 24,
    "draws": 8,
    "losses": 10,
    "whites": 20,
    "blacks": 22,
    "win_pct": 57,
    "avg_elo": 2450,
    "tree": {
        "games": 42,
        "wins": 24,
        "draws": 8,
        "losses": 10,
        "whites": 20,
        "blacks": 22,
        "children": {
            "e4": {
                "games": 42,
                "wins": 24,
                "draws": 8,
                "losses": 10,
                "whites": 20,
                "blacks": 22,
                "children": {
                    "e5": { ... },
                    "e6": { ... },
                }
            }
        }
    }
}
```

Each node tracks: `games`, `wins`, `draws`, `losses`, `whites`, `blacks`, `children` (dict of SAN move → child node).

### Algorithm
1. Parse filtered PGN (games matching the player's FIDE ID)
2. For each game, extract SAN move list via `chess.pgn.Game.mainline_variations()`
3. Group by `(opening, eco)` key (same as current `collect_opening_stats`)
4. For each group, build nested tree by traversing moves 0..`TREE_DEPTH-1`
5. At each node, accumulate `games/wins/draws/losses/whites/blacks`
6. Outcome determination: same logic as current stats (W/D/L based on `Result` header and player color)
7. Children are sorted by `games` descending; top `TREE_TOP_N` marked `visible: true`, rest `visible: false`

### Integration
- `collect_opening_stats()` gains a `tree` key per opening entry
- Called once on the combined filtered PGN at the end of the fetch flow (same as current behavior)
- No change to existing stats fields or SSE event structure — only the `tree` key is added

### Error Handling
- Games shorter than `TREE_DEPTH` plies: tree stops at last move (no children)
- Malformed moves or PGN: silently skipped (same as current `filter_and_collect_stats` exception handling)
- Empty PGN: returns empty list (same as current)

## Frontend

### HTML Structure
Each opening row in the stats table gains a nested expandable section:

```html
<tr class="opening-row" data-opening="Ruy Lopez">
  <!-- existing cells -->
  <td colspan="10" class="tree-cell">
    <details class="move-tree">
      <summary class="tree-toggle">Move Tree</summary>
      <div class="tree-content">
        <ul class="tree-level">
          <li>
            <span class="tree-node tree-visible">e4 <span class="tree-stats">(42, 57%, ⬜:62% ⬛:52%)</span></span>
            <ul class="tree-level">
              <li>
                <span class="tree-node tree-visible">e5 <span class="tree-stats">(40, 55%, ⬜:60% ⬛:50%)</span></span>
                <ul class="tree-level">...</ul>
              </li>
              <!-- collapsed child -->
              <li>
                <details class="tree-collapsed">
                  <summary>… and 2 more</summary>
                  <ul class="tree-level">...</ul>
                </details>
              </li>
            </ul>
          </li>
        </ul>
      </div>
    </details>
  </td>
</tr>
```

### Rendering
- `renderStats()` in `app.js` receives the `tree` key from SSE `done` event
- New function `renderTree(node, depth)` recursively builds nested `<ul>` elements
- At each level, children sorted by `games` desc; first `TREE_TOP_N` rendered directly, rest wrapped in `<details class="tree-collapsed">`
- Win rate calculated per-node: `round(wins/games * 100)`
- Color-split win rates: `⬜: round(white_wins/white_games * 100)` and `⬛: round(black_wins/black_games * 100)`; shown as `-` when count is 0

### Styling
- Nested `<ul>` with left border lines (CSS `border-left: 2px solid #ddd`)
- Tree nodes display move in bold, stats in smaller text
- Collapsed section uses native `<details>`/`<summary>` for click-to-expand
- Consistent with existing table styling

## Testing
- Unit test: `build_opening_tree` with sample PGN — verify tree structure, stats, depth limit, top-N collapse
- Unit test: short games (fewer moves than `TREE_DEPTH`) — tree stops gracefully
- Unit test: empty PGN — returns empty list
- Unit test: single game — tree has one path
- Integration test: mock SSE response with tree data — verify frontend renders correctly

## Files Affected
| File | Change |
|------|--------|
| `pgn_processor.py` | Add `TREE_DEPTH`, `TREE_TOP_N` constants; new `build_opening_tree()` function; integrate into `collect_opening_stats()` |
| `static/app.js` | New `renderTree()` function; update `renderStats()` to include tree in each row |
| `static/style.css` | Tree node styling, nested list indentation, collapsed details styling |
| `templates/index.html` | No changes (tree rendered inside existing table rows) |
| `tests/test_pgn_processor.py` | Tests for `build_opening_tree` |

## Out of Scope
- Interactive board showing moves (F4)
- Filtering by color or date range
- Exporting tree data
- Caching tree separately from stats
