# Opening Repertoire Tree Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Add expandable move trees to the opening stats table.

**Architecture:** Backend builds nested tree from PGN moves, grouped by opening. Frontend renders each tree as expandable `<details>` inside each stats row. Per-color W/D/L enables color-split win rates.

**Tech Stack:** Python (chess.pgn), Flask, vanilla JS, CSS

---

## Chunk 1: Backend

### Task 1: Add constants

**Files:** Modify `pgn_processor.py:14`

- [ ] Add after `_TOURNAMENT_ID_RE`:
```python
TREE_DEPTH = 6  # max plies from opening root
```
Note: `TREE_TOP_N` is a frontend-only constant (in `static/app.js`).
- [ ] Commit: `git add pgn_processor.py && git commit -m "feat: add tree constants"`

### Task 2: Write failing tests

**Files:** Modify `tests/test_pgn_processor.py` (append)

- [ ] Append test class `TestBuildOpeningTree` with 7 tests:
  - `test_basic_tree` - single game, verify tree structure, children dict
  - `test_accumulation` - two games same opening, verify games/wins/whites/blacks
  - `test_per_color_breakdown` - white wins as white, black loses as black
  - `test_depth_limit` - game with 10+ plies, assert tree depth <= TREE_DEPTH (6)
  - `test_short_game` - 1 move game, tree stops gracefully
  - `test_empty_pgn` - empty string returns []
  - `test_non_matching_fide` - different FIDE returns []

  PGN fixtures use minimal headers: Event, Site, Date, Round, White, Black, Result, WhiteFideId, BlackFideId, ECO, Opening.

- [ ] Run: `pytest tests/test_pgn_processor.py::TestBuildOpeningTree -v` (expect FAIL)
- [ ] Commit: `git add tests/test_pgn_processor.py && git commit -m "test: add failing tests for build_opening_tree"`

### Task 3: Implement build_opening_tree

**Files:** Modify `pgn_processor.py` (add after `collect_opening_stats`, ~line 788)

- [ ] Add helpers and main function:
```python
def _make_tree_node():
    return {
        "games": 0, "wins": 0, "draws": 0, "losses": 0,
        "whites": 0, "blacks": 0,
        "white_wins": 0, "white_draws": 0, "white_losses": 0,
        "black_wins": 0, "black_draws": 0, "black_losses": 0,
        "children": {},
    }

def _accumulate_node(node, outcome, is_white):
    node["games"] += 1
    node["wins" if outcome == "W" else "draws" if outcome == "D" else "losses"] += 1
    color = "white" if is_white else "black"
    node[color + "s"] += 1
    node[color + "_" + ("wins" if outcome == "W" else "draws" if outcome == "D" else "losses")] += 1

def _sort_tree_children(node):
    node["children"] = dict(sorted(node["children"].items(), key=lambda x: x[1]["games"], reverse=True))
    for child in node["children"].values():
        _sort_tree_children(child)

def build_opening_tree(pgn_text, fide_id):
    """Build move trees for each opening. Returns list sorted by games desc."""
    if not pgn_text:
        return []
    openings = {}
    stream = io.StringIO(pgn_text)
    while True:
        try:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            headers = game.headers
            wf = headers.get("WhiteFideId", "")
            bf = headers.get("BlackFideId", "")
            if wf != fide_id and bf != fide_id:
                continue
            is_white = wf == fide_id
            result = headers.get("Result", "*")
            outcome = ("W" if result == "1-0" else "L" if result == "0-1" else "D") if is_white else ("W" if result == "0-1" else "L" if result == "1-0" else "D")
            eco = headers.get("ECO", "")
            opening = headers.get("Opening", "") or _get_eco_openings().get(eco, f"ECO {eco}") if eco else "Unknown"
            key = (opening, eco)
            if key not in openings:
                node = _make_tree_node()
                node["opening"] = opening
                node["eco"] = eco
                openings[key] = node
            tree = openings[key]
            _accumulate_node(tree, outcome, is_white)
            board = game.board()
            for depth, move in enumerate(game.mainline_variations()):
                if depth >= TREE_DEPTH:
                    break
                san = board.san(move)
                if san not in tree["children"]:
                    tree["children"][san] = _make_tree_node()
                tree = tree["children"][san]
                _accumulate_node(tree, outcome, is_white)
                board.push(move)
        except Exception:
            continue
    result = sorted(openings.values(), key=lambda x: x["games"], reverse=True)
    for entry in result:
        _sort_tree_children(entry)
    return result
```
- [ ] Run: `pytest tests/test_pgn_processor.py::TestBuildOpeningTree -v` (expect PASS)
- [ ] Commit: `git add pgn_processor.py && git commit -m "feat: implement build_opening_tree"`

### Task 4: Integrate into collect_opening_stats

**Files:** Modify `pgn_processor.py:760-788` (return block of `collect_opening_stats`)

- [ ] Replace final return with:
```python
    result_list.sort(key=lambda x: x["games"], reverse=True)
    tree_results = build_opening_tree(pgn_text, fide_id)
    tree_by_key = {(e["opening"], e["eco"]): e for e in tree_results}
    for entry in result_list:
        entry["tree"] = tree_by_key.get((entry["opening"], entry["eco"]), {})
    return {"stats": result_list, "player_name": player_name or ""}
```
- [ ] Add quick smoke test to verify tree key exists:
```python
    def test_collect_stats_includes_tree(self):
        pgn = """[Event "T1"][Site "?"][Date "2024.01.01"][Round "?"]
[White "A"][Black "B"][Result "1-0"]
[WhiteFideId "1234567"][BlackFideId "7654321"]
[ECO "C65"][Opening "Ruy Lopez"]

1. e4 e5 1-0"""
        from pgn_processor import collect_opening_stats
        result = collect_opening_stats(pgn, "1234567")
        assert "stats" in result
        assert len(result["stats"]) == 1
        assert "tree" in result["stats"][0]
        assert "children" in result["stats"][0]["tree"]
```
- [ ] Run: `pytest tests/test_pgn_processor.py -v` (expect all PASS)
- [ ] Commit: `git add pgn_processor.py && git commit -m "feat: attach tree to collect_opening_stats"`

---

## Chunk 2: Frontend

### Task 5: Add CSS

**Files:** Modify `static/style.css` (append)

- [ ] Append:
```css
.tree-cell{padding:0}.move-tree{margin:0}.tree-toggle{padding:8px 16px;cursor:pointer;font-size:.9em;color:#666;background:#f9f9f9;border-top:1px solid #eee}.tree-toggle:hover{background:#f0f0f0}.tree-content{padding:8px 16px 16px;background:#fafafa;border-top:1px solid #eee;overflow-x:auto}.tree-level{list-style:none;padding-left:20px;margin:2px 0}.tree-level .tree-level{border-left:2px solid #ddd;margin-left:4px}.tree-node{display:inline-block;padding:1px 0;font-family:monospace;font-size:.9em}.tree-move{font-weight:bold}.tree-stats{color:#888;font-size:.85em;margin-left:4px}.tree-collapsed{margin:2px 0 2px 20px}.tree-collapsed summary{cursor:pointer;font-size:.85em;color:#999;padding:2px 0}.tree-collapsed summary:hover{color:#666}
```
- [ ] Commit: `git add static/style.css && git commit -m "style: add move tree CSS"`

### Task 6: Add JS rendering

**Files:** Modify `static/app.js` (add before `renderStatsRows`, update it)

- [ ] Add before `renderStatsRows` (~line 242):
```javascript
const TREE_TOP_N = 5;
function _cwr(n,c){var w=c==="w"?n.white_wins:n.black_wins,t=c==="w"?n.whites:n.blacks;return t>0?Math.round(w/t*100)+"%":"-";}
function _tn(m,n){var s=document.createElement('span');s.className='tree-node';var ms=document.createElement('span');ms.className='tree-move';ms.textContent=m;s.appendChild(ms);var st=document.createElement('span');st.className='tree-stats';var wr=n.games>0?Math.round(n.wins/n.games*100)+"%":"-";st.textContent="("+n.games+", "+wr+", \u25A1:"+_cwr(n,"w")+"\u25A0:"+_cwr(n,"b")+")";s.appendChild(st);return s;}
function renderTree(tree){if(!tree||!tree.children)return document.createTextNode('No moves');var ul=document.createElement('ul');ul.className='tree-level';var e=Object.entries(tree.children);for(var i=0;i<TREE_TOP_N&&i<e.length;i++){var li=document.createElement('li');li.appendChild(_tn(e[i][0],e[i][1]));if(e[i][1].children&&Object.keys(e[i][1].children).length>0)li.appendChild(renderTree(e[i][1]));ul.appendChild(li);}if(e.length>TREE_TOP_N){var co=document.createElement('li'),d=document.createElement('details');d.className='tree-collapsed';var su=document.createElement('summary');su.textContent="... and "+(e.length-TREE_TOP_N)+" more";d.appendChild(su);var su2=document.createElement('ul');su2.className='tree-level';for(var j=TREE_TOP_N;j<e.length;j++){var li2=document.createElement('li');li2.appendChild(_tn(e[j][0],e[j][1]));if(e[j][1].children&&Object.keys(e[j][1].children).length>0)li2.appendChild(renderTree(e[j][1]));su2.appendChild(li2);}d.appendChild(su2);co.appendChild(d);ul.appendChild(co);}return ul;}
```
- [ ] Update `renderStatsRows` - inside the `data.forEach(s => {` loop, after `statsTableBody.appendChild(tr)`, add:
```javascript
        var tr2 = document.createElement('tr');
        var td = document.createElement('td');
        td.className = 'tree-cell';
        td.colSpan = 10;
        var det = document.createElement('details');
        det.className = 'move-tree';
        var sum = document.createElement('summary');
        sum.className = 'tree-toggle';
        sum.textContent = 'Move Tree';
        det.appendChild(sum);
        var con = document.createElement('div');
        con.className = 'tree-content';
        con.appendChild(renderTree(s.tree));
        det.appendChild(con);
        td.appendChild(det);
        tr2.appendChild(td);
        statsTableBody.appendChild(tr2);
```
Location: `static/app.js` inside `renderStatsRows`, after the existing `statsTableBody.appendChild(tr)` line (~line 260).
- [ ] Commit: `git add static/app.js && git commit -m "feat: add tree rendering to stats table"`

### Task 7: Verify full flow

Note: Automated frontend tests for `renderTree` collapse logic and SSE integration are not feasible without a DOM test framework (e.g. jsdom). Manual verification in Task 7 covers these cases.

- [ ] Run: `pytest -v` (expect all 86+ tests PASS)
- [ ] Run: `python app.py` locally, verify:
  (a) tree `<details>` appears per opening row
  (b) top 5 moves visible at each level
  (c) "... and X more" expands to show remaining moves
  (d) per-color win rates display (⬜/⬛ percentages)
  (e) tree stops at 6 plies max
- [ ] Commit: `git add -A && git commit -m "feat: opening repertoire tree complete"`
