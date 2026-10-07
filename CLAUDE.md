# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

象棋师父 · Xiangqi Shifu — a Chinese chess coach. Play a move and get a verdict, a Chinese explanation naming the piece/attacker/cost, and the engine's top 3 alternatives. FastAPI backend + React/Vite frontend + Pikafish (external process, GPL-3.0, downloaded at setup, not bundled).

**All analysis is deterministic and rule-based — there are no LLM calls anywhere in the analysis path**, and that is a deliberate design property (reproducible, cannot hallucinate a threat). Coaching prose is assembled from board facts in `backend/app/analysis/explain.py`. Do not introduce model calls to generate or smooth the text.

All player-facing strings are Chinese; code, comments, identifiers, and commit messages are English.

## Commands

Engine (needed by the backend; macOS/Linux only script):

```bash
./scripts/setup_engine.sh     # → engine/pikafish + engine/pikafish.nnue
```

Backend — run from `backend/` (tests import `app.*`, so the working directory matters):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                          # full suite
pytest tests/test_game.py::test_undo_reverts_board_and_history -q   # one test
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend — run from `frontend/`:

```bash
npm install
npm run dev                                   # http://localhost:5173
npx tsc -b && npx oxlint .                    # typecheck + lint (npm run build = tsc -b && vite build)
```

Env vars: `ENGINE_PATH`, `ENGINE_DEPTH` (default 14), `ENGINE_MULTIPV` (default 3) on the backend; `VITE_API_BASE_URL` on the frontend.

### Testing notes

- `backend/tests/test_ucci.py` shells out to the real Pikafish binary and `pytest.mark.skipif`s on its absence — those are the only slow/conditional tests; everything else is fast unit tests using `FakeEngine` stubs (see `test_game.py`).
- There is no Python linter configured. Frontend is typechecked with `tsc -b` and linted with oxlint.
- On Windows the binary is `engine/pikafish.exe` and the default `ENGINE_PATH` (`<repo>/engine/pikafish`) does not resolve — set `ENGINE_PATH=.../engine/pikafish.exe`. Note `.gitignore` covers `engine/pikafish` but **not** `pikafish.exe`, so it shows as untracked; don't commit the binary or the 50 MB `.nnue`.
- With a current Pikafish build, `test_engine_reports_mate_scores` fails: its FEN contains three red chariots, which newer Pikafish rejects as an unsupported position (and then exits). Pre-existing, unrelated to game logic.

## Architecture

Backend layering, dependency-free at the bottom:

```
xiangqi/      pure board + rules (no engine, no I/O)
engine/ucci.py  subprocess client for Pikafish
analysis/     classify · tactics · intent · openings · explain  (deterministic, pure)
game.py       GameSession — orchestrates board state + engine + analysis
library/      record model + on-disk game store (data/games/*.json)
api/routes.py thin HTTP layer; schemas.py is the wire contract
```

**Coordinates.** Two conventions coexist and invert relative to each other:
`Board` grid is `(row, col)` with row 0 = **black's** back rank (FEN rank order);
`Move.to_uci()` is file `a`–`i` + rank `0`–`9` with rank 0 = **red's** back rank
(`rank = 9 - row`). Piece letters are the usual Xiangqi FEN set: `K A B N R C P`, uppercase = red.

**中文记谱法 is the central abstraction** (`xiangqi/notation.py`). Every user-visible move — and every piece reference in the coaching text, e.g. 七路兵（c4） — goes through it. Red counts files 一…九 from its own right (`file = 9 - col`), black counts １…９ (`file = col + 1`); the frontend mirrors the same numerals in `frontend/src/board/constants.ts`. `move_to_chinese(board, move)` needs the board **before** the move is applied, and disambiguation (前/后/中) is derived from stacks on the file. `chinese_to_move` parses only by round-tripping against legal moves, so notation that is ambiguous or non-unique raises. `tests/test_notation.py` re-renders every opening-book line and asserts uniqueness across all legal moves in several positions — run it after any notation change.

**Engine protocol** (`engine/ucci.py`): despite the name, Pikafish is Stockfish-derived and speaks **UCI** (`uci`, `position fen ... moves ...`, `go depth N`, `setoption name MultiPV`, `info ... score cp|mate ... pv ...`). One shared process guarded by an `RLock`; `analyze()` holds it across MultiPV, position, and read-to-`bestmove` so concurrent requests can't interleave. `GameSession` sends the **full move history** (`position fen <start> moves ...`) rather than a bare current FEN, because the engine needs the repetition history to apply 长将 rules correctly.

**`GameSession`** (`game.py`) is one in-memory game plus an auto-saving record. It holds a `threading.RLock` because FastAPI runs sync endpoints in a threadpool. `_cached_lines` stores the analysis of the current position so the next move's "before" search is reused: a normal move costs one search, not two. `redo_stack` + `move_history` back 悔棋/重做/goto; playing a genuinely new move discards the redo stack. Notes are parallel stacks — `move_notes` mirrors `move_history`, `redo_notes` mirrors `redo_stack` — so a note can never drift to a different ply. Constructed with a `GameStore`, every mutation (move/undo/redo/goto/`set_note`) rewrites the applied line to `data/games/<id>.json` through `_persist`, creating the record lazily on the first move; a failed write sets `save_error` and leaves the move standing in memory. Opening a game does not write — 打开 must not bump the file's `updated_at` (the library sorts on it) — while 导入 writes the new record exactly once, so an imported game's `updated_at` is its import time; a session built with `store=None` stays purely in memory (what the tests use). The record carries moves, notes and a result snapshot but **no engine output**: that is large, recomputable, and would make an exported file brittle.

**Scoring perspectives are easy to get backwards** (full table in `docs/api-contract.md`):
`eval_cp` is from **red's** perspective (eval bar never flips); `candidates[].score_cp` is from the **mover's** perspective (the side to move *before* the played move); `lines[]` is raw engine output. Classification (`analysis/classify.py`) normalizes everything to the mover: `cp_loss` thresholds → 最佳/优秀/好棋/不太准确/失误/大漏着, with mate scores mapped to `MATE_SCORE = 100_000` so they dominate. A game-ending move is always `cp_loss == 0` — a terminal position yields no engine lines, which previously read as eval 0 and scored a winning mate as a 99999 cp blunder.

**Tactic detection** (`analysis/tactics.py`) is deliberately conservative: real static exchange evaluation (x-ray aware, first capture legality-checked so a pinned attacker is not a threat) plus fork/pin/空头炮 detection. Only losses above `SEE_REPORT_THRESHOLD = 1.5` pawns are reported — below that is ordinary pawn tension, and a warning that fires every move is noise an experienced player ignores. Adding a tactic kind means touching four places: the detector, `explain._tactic_sentence`, `_PROBLEM_PRIORITY`, and the merit/why-better branches in `explain.py`; then the frontend `Tactic` type.

**Coaching text** (`analysis/explain.py`) turns facts into prose under two rules stated at the top of the file: never contradict itself (warnings after a good move are softened to 「要注意」 rather than framed as faults), and say what a move *did* (a quiet move still gets a positional reason from `_goal_fragments`). Intent rows come from `analysis/intent.py` — the facts (what the move attacks, saves, or is for) — and are rendered into the `intents` rows and the embedded `intent_text` sentence by `explain.py`; adding an intent kind touches the detector, the wording tables in `explain.py`, and the frontend `Intent` type. `find_opening` (`analysis/openings.py`) does longest-prefix matching over a curated book; `left_book_now` is true **only** on the exact diverging ply, so the coach says it once.

**Frontend** is a single non-scrolling screen. `state/useGame.ts` is the core: a `Timeline { moves, pointer, viewPly }` where `pointer` is how much is applied to the live backend board and `viewPly` is purely which ply the UI displays — history browsing never calls the backend, which is why `api.goto` exists server-side but is deliberately not exposed in `api/client.ts`. `autoPlayArmed` gates the engine auto-move: it is disarmed by 悔棋/重做 and re-armed only by a deliberate act (playing a move, engine-move, new game, controller change) — without it, undoing in an engine game instantly hands the turn back and the engine replays the move you just took back. `useBoardFit.ts` sizes the board as the only element that absorbs slack; its `RESERVED_W`/`RESERVED_H` constants must stay in sync with the panel minimum widths in `index.css`. `ConceptPanel` strips `why_better`/`intent_text`/`opening_note` back out of the `explanation` paragraph when rendering them as separate blocks — server-side strings must stay verbatim-embedded for that to work. `MoveResultResponse.side_to_move` is the side to move **after** the move; the mover is `otherSide(side_to_move)`.

`docs/api-contract.md` is the contract the frontend is written against — update it alongside any response-shape change.

## Rules scope

Implemented: flying-general (白脸将), 困毙 as a **loss** (not a draw), 长将判负, repetition draw. 长捉 and 长兑 are deliberately **not** implemented — judging them correctly needs rulings on protected-piece and genuine-threat semantics where a naive version confidently returns wrong verdicts; those games report `draw_repetition`. Don't add them without handling those cases.
