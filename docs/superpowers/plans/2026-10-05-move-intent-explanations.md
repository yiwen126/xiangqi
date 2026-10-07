# Move-intent Explanations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every played move gets a deterministic "intent" layer — which enemy piece it attacks, which of ours it saves, and what it is for — plus the engine's expected continuation, rendered in Chinese in the 讲解 card.

**Architecture:** A new pure detector (`analysis/intent.py`) computes attack/defense facts from board state using the existing SEE machinery; `analysis/explain.py` renders them into 攻/守/目的 rows and one paragraph sentence; `game.py` passes them through and adds `follow_up` built from the already-computed after-move engine PV; `ConceptPanel` renders two new blocks.

**Tech Stack:** Python 3 / FastAPI / pydantic v2 / pytest (backend); React + TypeScript + Vite, `tsc -b` + oxlint (frontend).

**Spec:** `docs/superpowers/specs/2026-10-05-move-intent-explanation-design.md`

## Global Constraints

- No LLM anywhere; prose is assembled from board facts and raw engine output.
- Deterministic; **no new engine searches** — reuse `_cached_lines` / `lines_after`; the PV is display-only and never paraphrased into claims.
- Player-facing strings Chinese; code, comments, identifiers, commit messages English.
- Backend tests run from `backend/` (`pytest -q`); frontend check from `frontend/` (`npx tsc -b && npx oxlint .`).
- Constants: `ATTACK_EVEN_MIN_VALUE = 4.0`, `DEFEND_MIN_VALUE = 2.0`, `MAX_ATTACK_ROWS = 2`, `MAX_DEFEND_ROWS = 2` (in `intent.py`); `FOLLOW_UP_PLIES = 4` (in `game.py`); reuse `SEE_REPORT_THRESHOLD = 1.5`.
- Wire changes update `docs/api-contract.md` in the same change.
- Commits go to `main` (repo habit, user approved); one commit per task.
- `CLAUDE.md` is untracked in this repo — edit it in Task 6 but do **not** `git add` it.

## Review Focus

1. A capturing move that removes a threatener — threat text must be read from the **before** board (Task 3: `test_defend_by_capture_still_reads_the_threat_from_the_before_board`).
2. A move that gives check — the general must never appear as an attack target (Task 1: `test_the_general_is_never_an_attack_target`).
3. Engine returns no PV moves — `follow_up` must be `None`, not a crash (Task 4: `test_follow_up_is_none_without_engine_lines`).
4. The game ends on the played move — `intents == []`, `intent_text is None`, `follow_up is None` (Task 3 terminal test, Task 4 mate test).
5. A PV longer than the display window — truncated to `FOLLOW_UP_PLIES` (Task 4: `test_follow_up_shows_the_expected_continuation_in_chinese`).

---

### Task 1: Attack detection + promote tactics helpers

**Files:**
- Modify: `backend/app/analysis/tactics.py` (rename `_capture_is_legal` → `capture_is_legal`, `_defenders` → `defenders_of`, update all call sites)
- Create: `backend/app/analysis/intent.py`
- Test: `backend/tests/test_intent.py`

**Interfaces:**
- Consumes: `tactics.attackers_of`, `tactics.capture_is_legal`, `tactics.defenders_of`, `tactics.static_exchange_eval`, `tactics.piece_value`, `tactics.SEE_REPORT_THRESHOLD`; `xiangqi.board.Board/Move/other_side/piece_color`.
- Produces: `IntentTag(kind, piece, piece_sq, target_sqs, detail)`; `new_attacks(board_before: Board, board_after: Board, move: Move) -> list[IntentTag]`; constants `ATTACK_EVEN_MIN_VALUE`, `DEFEND_MIN_VALUE`, `MAX_ATTACK_ROWS`, `MAX_DEFEND_ROWS`. Attack tags: `detail = {"tier": "win"|"even", "see": float, "defended": bool}`, one tag per victim, `target_sqs == [victim]`.

- [ ] **Step 1: Promote the two private helpers in `tactics.py`**

Rename the definitions and every call site (module-internal only; no test changes needed).

- [ ] **Step 2: Run the existing tactics tests**

Run (from `backend/`): `pytest tests/test_tactics.py -q`
Expected: all pass (pure rename).

- [ ] **Step 3: Write the failing tests**

```python
"""Move-intent detection: attack facts first (defense facts live in Task 2)."""
from app.analysis.intent import new_attacks
from app.analysis.tactics import capture_is_legal
from app.xiangqi.board import Board, Move
from app.xiangqi.movegen import is_in_check


def attack_tags(fen: str, uci: str):
    before = Board.from_fen(fen)
    move = Move.from_uci(uci)
    after = before.clone()
    after.apply_move(move)
    return new_attacks(before, after, move)


def test_new_contact_on_undefended_horse_is_a_win_attack():
    tags = attack_tags("4k4/9/9/9/R8/3n5/9/9/9/3K5 w - - 0 1", "a5d5")
    assert len(tags) == 1
    tag = tags[0]
    assert tag.kind == "attack"
    assert tag.piece == "R"
    assert tag.piece_sq == (4, 3)
    assert tag.target_sqs == [(5, 3)]
    assert tag.detail == {"tier": "win", "see": 4.0, "defended": False}


def test_attack_on_a_defended_chariot_is_win_tier_with_net_gain():
    # The horse lands on d3; its attack on the chariot on e5 is worth 5 pawns
    # after the pawn recaptures.
    tags = attack_tags("4k4/9/9/4p4/4r4/9/9/9/2N6/3K5 w - - 0 1", "c1d3")
    assert len(tags) == 1
    assert tags[0].detail == {"tier": "win", "see": 5.0, "defended": True}


def test_attack_on_a_defended_horse_is_an_even_exchange_offer():
    tags = attack_tags("4k4/9/9/4p4/4n4/9/9/9/2N6/3K5 w - - 0 1", "c1d3")
    assert len(tags) == 1
    assert tags[0].detail == {"tier": "even", "see": 0.0, "defended": True}


def test_preexisting_contact_is_not_reported():
    # The chariot already attacked the horse on d4 before the general moved.
    assert attack_tags("4k4/9/9/9/9/R2n5/9/9/9/3K5 w - - 0 1", "d0d1") == []


def test_capturing_move_never_names_the_captured_piece():
    # a4d4 captures the pawn on d4 and only then attacks the horse on g4.
    tags = attack_tags("4k4/9/9/9/9/R2p2n2/9/9/9/3K5 w - - 0 1", "a4d4")
    assert [t.target_sqs[0] for t in tags] == [(5, 6)]


def test_standoff_with_a_more_valuable_attacker_is_not_reported():
    # A chariot poking a defended horse reaches SEE 0 by declining the trade;
    # that is not pressure and must not be worded as an exchange offer.
    assert attack_tags("4k4/9/9/4p4/4n4/9/9/9/R8/3K5 w - - 0 1", "a1e1") == []


def test_pawn_targets_are_below_the_pressure_threshold():
    assert attack_tags("4k4/9/9/9/4p4/9/9/9/R8/3K5 w - - 0 1", "a1e1") == []


def test_pinned_attacker_does_not_create_a_threat():
    # Black chariot on e5 is pinned against its general by the red chariot on
    # e1; its "attack" on the red horse on g5 is not a real threat.
    before = Board.from_fen("4k4/9/9/9/4r1N2/p8/9/9/4R4/3K5 b - - 0 1")
    assert capture_is_legal(before, (4, 4), (4, 6)) is False
    assert attack_tags("4k4/9/9/9/4r1N2/p8/9/9/4R4/3K5 b - - 0 1", "a4a3") == []


def test_the_general_is_never_an_attack_target():
    before = Board.from_fen("4k4/9/9/9/9/9/9/9/9/3KR4 w - - 0 1")
    move = Move.from_uci("e0e8")
    after = before.clone()
    after.apply_move(move)
    assert is_in_check(after, "b") is True  # 车一进九: that is 将军, not an attack row
    assert new_attacks(before, after, move) == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run (from `backend/`): `pytest tests/test_intent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.intent'`.

- [ ] **Step 5: Implement the attack half of `intent.py`**

Signatures:

```python
ATTACK_EVEN_MIN_VALUE = 4.0
DEFEND_MIN_VALUE = 2.0
MAX_ATTACK_ROWS = 2
MAX_DEFEND_ROWS = 2


@dataclass
class IntentTag:
    kind: str  # "attack" | "defend"
    piece: str
    piece_sq: tuple[int, int]
    target_sqs: list[tuple[int, int]] = field(default_factory=list)
    detail: dict = field(default_factory=dict)
```

Algorithm for `new_attacks(before, after, move)` — scan every square of the
**after** board; skip empties, the mover's own pieces, and generals (攻击将帅 is
将军); for each remaining victim square `sq`:

1. `attackers = [a for a in attackers_of(after, sq, mover) if capture_is_legal(after, a, sq)]`; skip when empty (a pinned attacker is not a threat).
2. `see_after = static_exchange_eval(after, sq, mover)`, `see_before = static_exchange_eval(before, sq, mover)`.
3. Triggers: `newly_contacted = not legal_attackers(before)` or `newly_winnable = see_before < SEE_REPORT_THRESHOLD <= see_after`; skip when neither (pre-existing contact is never re-announced).
4. Attributed attacker: `move.to_sq` when it is among `attackers`, else the smallest-value attacker.
5. Tier: `win` when `see_after >= SEE_REPORT_THRESHOLD`; else `even` when `see_after < SEE_REPORT_THRESHOLD` and victim value ≥ `ATTACK_EVEN_MIN_VALUE` and victim value ≥ attacker value; else skip.
6. Emit one tag per victim: `piece` = attacker letter (on the after board), `piece_sq` = attacker square, `target_sqs = [sq]`, `detail = {"tier", "see": see_after, "defended": bool(defenders_of(after, sq, other_side(mover)))}`.

- [ ] **Step 6: Run the tests to verify they pass**

Run (from `backend/`): `pytest tests/test_intent.py tests/test_tactics.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis/intent.py backend/app/analysis/tactics.py backend/tests/test_intent.py
git commit -m "Add move-intent detection: attack facts"
```

---

### Task 2: Defenses, escapes, and `detect`

**Files:**
- Modify: `backend/app/analysis/intent.py`
- Test: `backend/tests/test_intent.py` (append)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces: `saved_pieces(board_before, board_after, move) -> list[IntentTag]` (defense tags: `detail = {"escape": bool, "see_before": float, "threat_uci": str}`, `target_sqs = [primary threatener]`; `piece_sq` is the saved piece's square on the **before** board — the mover's origin square when `escape` is true); `detect(board: Board, move: Move) -> list[IntentTag]` — attacks sorted (win before even, then victim value descending) and capped at `MAX_ATTACK_ROWS`, then defenses sorted by `see_before` descending and capped at `MAX_DEFEND_ROWS`.

- [ ] **Step 1: Write the failing tests**

```python
def test_defending_a_hanging_piece_reports_the_threat():
    tags = detect(Board.from_fen("3k5/9/9/9/9/2N6/9/9/r8/R3K4 w - - 0 1"), Move.from_uci("c4b2"))
    assert len(tags) == 1
    tag = tags[0]
    assert tag.kind == "defend"
    assert tag.piece == "R"
    assert tag.piece_sq == (9, 0)
    assert tag.target_sqs == [(8, 0)]
    assert tag.detail == {"escape": False, "see_before": 9.0, "threat_uci": "a1a0"}


def test_defend_by_capturing_the_threatener_still_names_the_threat():
    tags = detect(Board.from_fen("3k5/9/9/9/9/9/1N7/9/r8/R3K4 w - - 0 1"), Move.from_uci("b3a1"))
    assert len(tags) == 1
    assert tags[0].kind == "defend"
    assert tags[0].piece_sq == (9, 0)
    assert tags[0].detail["threat_uci"] == "a1a0"


def test_escape_from_an_attack_uses_the_origin_square():
    tags = detect(Board.from_fen("4k4/9/9/9/9/9/9/3K5/r8/R8 w - - 0 1"), Move.from_uci("a0i0"))
    assert len(tags) == 1
    tag = tags[0]
    assert tag.kind == "defend"
    assert tag.detail["escape"] is True
    assert tag.piece_sq == (9, 0)  # the square it left, not i0
    assert tag.detail["threat_uci"] == "a1a0"


def test_piece_that_stays_hanging_is_not_reported():
    # The chariot on a0 stays hanging; moving the general does not defend it.
    assert detect(Board.from_fen("3k5/9/9/9/9/9/9/9/r8/R3K4 w - - 0 1"), Move.from_uci("e0f0")) == []


def test_attacks_are_ranked_and_capped():
    tags = detect(Board.from_fen("4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1"), Move.from_uci("f2e4"))
    # Chariot 9.0 and cannon 4.5 first; the horse 4.0 is dropped by the cap.
    assert [t.target_sqs[0] for t in tags] == [(4, 6), (3, 5)]
    assert all(t.kind == "attack" and t.detail["tier"] == "win" for t in tags)


def test_detect_is_deterministic():
    fen, uci = "4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1", "f2e4"
    assert detect(Board.from_fen(fen), Move.from_uci(uci)) == detect(Board.from_fen(fen), Move.from_uci(uci))
```

Also add `detect` to the module's imports in the test file.

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `pytest tests/test_intent.py -q`
Expected: FAIL — `ImportError: cannot import name 'detect'`.

- [ ] **Step 3: Implement `saved_pieces` and `detect`**

`saved_pieces(before, after, move)` — mover = colour of `before.piece_at(move.from_sq)`, opponent = `other_side(mover)`. For every own piece `P` (skip empty, generals, `piece_value < DEFEND_MIN_VALUE`) whose `see_before = static_exchange_eval(before, sq, opponent) >= SEE_REPORT_THRESHOLD`:

- If `sq == move.from_sq` (the mover itself): escape case — evaluate `see_after` at `move.to_sq`.
- Otherwise evaluate `see_after` at `sq`.
- Skip when `see_after >= SEE_REPORT_THRESHOLD` (still losable, even if the loss shrank).
- Primary threatener = smallest-value legal attacker of `sq` on the **before** board; emit `IntentTag("defend", P, sq, [primary], {"escape": ..., "see_before": see_before, "threat_uci": Move(primary, sq).to_uci()})`.

`detect(board, move)` clones the board, applies the move, calls both detectors, sorts and caps as in the Interfaces block. The module docstring states the determinism/no-engine contract.

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`): `pytest tests/test_intent.py tests/test_tactics.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/intent.py backend/tests/test_intent.py
git commit -m "Add move-intent detection: defenses and escapes"
```

---

### Task 3: Render intents in `explain.py` and pass them through

**Files:**
- Modify: `backend/app/analysis/explain.py`
- Modify: `backend/app/game.py` (one line in `_play_move`)
- Test: `backend/tests/test_explain.py` (append)

**Interfaces:**
- Consumes: `intent.detect`, `IntentTag`.
- Produces: `build_explanation(...)` keeps its signature but its return dict drops `"move_merit"` and gains `"intents": list[dict]` and `"intent_text": str | None`. Row dicts (wire shape): `{"kind", "text", "piece", "piece_name", "square", "square_chinese", "targets", "targets_chinese"}`. `intent_text` is embedded verbatim in `"text"`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_explain.py` (reuse its existing `explain()` helper):

```python
def test_attack_row_names_the_victim_and_is_embedded_in_the_paragraph():
    out = explain("4k4/9/9/9/R8/3n5/9/9/9/3K5 w - - 0 1", "a5d5", matches_best=True)
    rows = out["intents"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "attack"
    assert rows[0]["text"] == "威胁白吃对方的４路马（d4）"
    assert rows[0]["targets_chinese"] == ["４路马（d4）"]
    assert out["intent_text"] == "这步意在威胁白吃对方的４路马（d4）。"
    assert out["intent_text"] in out["text"]


def test_defended_attack_uses_the_net_gain_wording():
    out = explain("4k4/9/9/4p4/4r4/9/9/9/2N6/3K5 w - - 0 1", "c1d3", matches_best=True)
    assert [r["text"] for r in out["intents"]] == ["威胁吃对方的５路车（e5），兑子后你净赚约 5 兵"]


def test_even_contact_uses_exchange_wording():
    out = explain("4k4/9/9/4p4/4n4/9/9/9/2N6/3K5 w - - 0 1", "c1d3", matches_best=True)
    assert [r["text"] for r in out["intents"]] == ["邀兑对方的５路马（e5），对方有子保护"]


def test_small_edge_pressure_uses_the_probing_wording():
    # Taking the defended cannon nets half a pawn after the pawn recaptures.
    out = explain("4k4/9/9/4p4/4c4/9/9/9/2N6/3K5 w - - 0 1", "c1d3", matches_best=True)
    assert [r["text"] for r in out["intents"]] == ["先手瞄住对方的５路炮（e5），兑子你稍占便宜"]


def test_hollow_cannon_is_an_attack_row():
    # 空头炮 aims at the general, so the move also gives check — both facts
    # must appear, hollow cannon first.
    out = explain("3k5/3a5/9/9/9/C8/9/9/3K5/9 w - - 0 1", "a4d4", matches_best=True)
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["attack", "goal"]
    assert rows[0]["text"] == "架起空头炮，直指对方中路"
    assert rows[1]["text"] == "将军，抢得先手"
    assert out["intent_text"] == "这步意在架起空头炮，直指对方中路；将军，抢得先手。"


def test_defense_row_names_the_threatening_move():
    out = explain("3k5/9/9/9/9/2N6/9/9/r8/R3K4 w - - 0 1", "c4b2", matches_best=True)
    rows = out["intents"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "defend"
    assert rows[0]["text"] == "保住九路车（a0），化解对方车１进１吃车的威胁"
    assert out["intent_text"] == "这步意在保住九路车（a0），化解对方车１进１吃车的威胁。"


def test_defend_by_capture_still_reads_the_threat_from_the_before_board():
    out = explain("3k5/9/9/9/9/9/1N7/9/r8/R3K4 w - - 0 1", "b3a1", matches_best=True)
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["defend", "goal"]
    assert rows[0]["text"] == "保住九路车（a0），化解对方车１进１吃车的威胁"
    assert rows[0]["targets_chinese"] == ["１路车（a1）"]  # read from the BEFORE board
    assert out["intent_text"] == "这步意在保住九路车（a0），化解对方车１进１吃车的威胁；吃掉对方的车。"


def test_escape_row_uses_the_origin_square():
    out = explain("4k4/9/9/9/9/9/9/3K5/r8/R8 w - - 0 1", "a0i0", matches_best=True)
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["defend", "goal"]
    assert rows[0]["text"] == "把受攻的九路车（a0）从对方攻击下走开"
    assert out["intent_text"] == "这步意在把受攻的九路车（a0）从对方攻击下走开；活通了车路，让车的出路更顺畅。"


def test_a_fork_merges_into_one_double_attack_row():
    out = explain("4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1", "f2e4", matches_best=True)
    rows = out["intents"]
    assert len(rows) == 1
    assert rows[0]["text"] == "形成双重攻击：对方的７路车（g5）和６路炮（f6）无法同时兼顾"
    assert rows[0]["targets_chinese"] == ["７路车（g5）", "６路炮（f6）"]


def test_blunder_still_gets_intents_without_praise():
    out = explain(None, "a0a1", cp_loss=400, best="h2e2")
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["goal"]
    assert out["intent_text"] == "这步意在把车从原位出动，加快大子的开发。"
    assert "稳健" not in out["text"]
    assert "大漏着" in out["text"]


def test_terminal_moves_have_no_intents():
    out = explain(
        "4k4/R8/1R6R/9/9/9/9/9/9/3K5 w - - 0 1", "i7i9",
        cp_loss=0, best="b7b9", terminal_status="checkmate",
    )
    assert out["intents"] == []
    assert out["intent_text"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `pytest tests/test_explain.py -q`
Expected: FAIL — `KeyError: 'intents'` (and new wording tests).

- [ ] **Step 3: Implement rendering in `explain.py`**

- `_format_pawns(value: float) -> str` — one decimal, trailing `.0` dropped (`2.0` → `2`, `4.5` → `4.5`).
- `_row(kind, text, board, piece, piece_sq, target_sqs) -> dict` — builds the wire dict; `square_chinese` and `targets_chinese` via `describe_piece(board, ...)`.
- `_attack_row(board_after, tag) -> dict` — wording per spec:
  - `win` + undefended: `威胁白吃对方的{describe_piece(victim)}`
  - `win` + defended: `威胁吃对方的{…}，兑子后你净赚约 {_format_pawns(see)} 兵`
  - `even`, `see == 0`: `邀兑对方的{…}，对方有子保护`
  - `even`, `see > 0`: `先手瞄住对方的{…}，兑子你稍占便宜`
- `_defend_row(board_before, tag) -> dict` — escape: `把受攻的{describe_piece(board_before, piece_sq)}从对方攻击下走开`; otherwise `保住{…}，化解对方{move_to_chinese(board_before, Move.from_uci(threat_uci))}吃{piece_name(victim)}的威胁`. All descriptions (saved piece **and** threatener) from `board_before`.
- `_intent_rows(board_before, board_after, move, tags, goal_fragments, new_gains) -> list[dict]` — group win-tier attack tags by attacker square; a group of ≥2 becomes one row at the first tag's position: `形成双重攻击：对方的{Ａ}和{Ｂ}无法同时兼顾` (victims in `targets`), others render individually; then a hollow-cannon row per hollow-cannon tag in `new_gains` (text `架起空头炮，直指对方中路`, `piece`/`square` = the cannon, `targets` = the general's square; `describe_piece` on the after board); then defend rows; then, when non-empty, one `goal` row (`piece`/`square` = moved piece at its destination, `targets = []`).
- `_goal_fragments(board_before, move, facts, opening, good_move, has_tactical_facts) -> list[str]` — replaces `_build_merit`; keeps check (`将军，抢得先手`), capture (`吃掉对方的{name}`) and the positional cascade; **deletes** the `resolved_problems` / hanging / fork / cannon-threat branches (superseded by intent rows — this also removes the old bug where a newly threatened piece was described with its attacker's square); in-book and the 稳健 fallback render only for good moves with no tactical rows; non-good moves get action facts only.
- `build_explanation` — when `terminal_status is None`: `tags = detect(board_before, move)`, `new_gains = facts["new_gains"]`, `has_tactical = bool(tags) or any(t.kind == "hollow_cannon" for t in new_gains)`, `goal_fragments = _goal_fragments(..., has_tactical)`, `intent_rows = _intent_rows(...)`, else `intent_rows = []`. `intent_text = "这步意在" + "；".join(r["text"] for r in intent_rows) + "。"` when rows exist, else `None`; append it right after the verdict sentence. Return dict: drop `"move_merit"`, add `"intents": intent_rows`, `"intent_text": intent_text`. Update the module docstring to mention the intent layer.

- [ ] **Step 4: Update `game.py`'s pass-through**

In `_play_move`'s return dict, replace `"move_merit": explanation["move_merit"],` with:

```python
"intents": explanation["intents"],
"intent_text": explanation["intent_text"],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `backend/`): `pytest tests/test_explain.py tests/test_game.py -q`
Expected: all pass (the game tests never asserted `move_merit`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/explain.py backend/app/game.py backend/tests/test_explain.py
git commit -m "Render move intents in the coaching text"
```

---

### Task 4: API fields, `follow_up`, and response-model validation

**Files:**
- Modify: `backend/app/api/schemas.py`, `backend/app/game.py`
- Test: `backend/tests/test_game.py` (append)

**Interfaces:**
- Consumes: Task 3's `intents` / `intent_text`.
- Produces: `IntentOut`, `FollowUpOut`; `MoveResultResponse` — removes `move_merit`, adds `intent_text: str | None`, `intents: list[IntentOut]`, `follow_up: FollowUpOut | None`; `game._follow_up_out(board, lines) -> dict | None`; `FOLLOW_UP_PLIES = 4`.

- [ ] **Step 1: Write the failing tests**

```python
from app.api.schemas import MoveResultResponse


class PvEngine:
    """Returns a fixed PV so follow-up rendering can be tested without the
    real engine."""

    def __init__(self, pv: list[str]):
        self.pv = pv

    def is_running(self) -> bool:
        return True

    def new_game(self) -> None:
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3) -> list[PvLine]:
        return [PvLine(multipv=1, score_cp=30, score_mate=None, pv=list(self.pv))]


def test_move_result_carries_intents_and_validates_against_schema(session: GameSession):
    result = session.make_move("h2", "e2")
    assert result["intents"], "炮二平五 should at least get a goal row"
    assert result["intent_text"] in result["explanation"]
    MoveResultResponse.model_validate(result)


def test_follow_up_shows_the_expected_continuation_in_chinese():
    session = GameSession(PvEngine(["h9g7", "h0g2", "b9c7", "c3c4", "c6c5"]))
    session.new_game()
    result = session.make_move("h2", "e2")
    assert result["follow_up"] == {
        "moves_uci": ["h9g7", "h0g2", "b9c7", "c3c4"],
        "moves_chinese": ["马８进７", "马二进三", "马２进３", "兵七进一"],
    }


def test_follow_up_pads_unrenderable_moves_with_null():
    session = GameSession(PvEngine(["h9g7", "a1a2"]))  # a1 is empty after 炮二平五
    session.new_game()
    result = session.make_move("h2", "e2")
    assert result["follow_up"] == {
        "moves_uci": ["h9g7", "a1a2"],
        "moves_chinese": ["马８进７", None],
    }


def test_follow_up_is_none_without_engine_lines(session: GameSession):
    result = session.make_move("h2", "e2")
    assert result["follow_up"] is None


def test_follow_up_and_intents_are_empty_when_the_game_ends():
    session = GameSession(MateScoringEngine(best_move="b7b9"))
    session.new_game(TWO_MATES_FEN)
    result = session.make_move("i7", "i9")
    assert result["follow_up"] is None
    assert result["intents"] == []
    assert result["intent_text"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `pytest tests/test_game.py -q`
Expected: FAIL — `ImportError: cannot import name 'MoveResultResponse'` is fine to hit first; after importing, missing `follow_up` keys.

- [ ] **Step 3: Implement the schemas and `follow_up`**

`schemas.py`:

```python
class IntentOut(BaseModel):
    kind: str  # attack | defend | goal
    text: str
    piece: str
    piece_name: str
    square: str
    square_chinese: str
    targets: list[str]
    targets_chinese: list[str]


class FollowUpOut(BaseModel):
    moves_uci: list[str]
    moves_chinese: list[str | None]
```

`MoveResultResponse`: remove `move_merit`, add `intent_text: str | None`, `intents: list[IntentOut]`, `follow_up: FollowUpOut | None`.

`game.py`:

```python
FOLLOW_UP_PLIES = 4  # how much of the after-move principal variation to show


def _follow_up_out(board: Board, lines: list[PvLine]) -> dict | None:
    if not lines or not lines[0].pv:
        return None
    pv = lines[0].pv[:FOLLOW_UP_PLIES]
    chinese = moves_to_chinese(board, pv)
    chinese += [None] * (len(pv) - len(chinese))  # keep indices aligned
    return {"moves_uci": pv, "moves_chinese": chinese}
```

and in `_play_move`'s return dict: `"follow_up": _follow_up_out(self.board, lines_after),` (the terminal branch leaves `lines_after == []`, so it is `None` there).

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`): `pytest tests/test_game.py tests/test_explain.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `pytest -q`
Expected: all pass (excluding the pre-existing, slow `test_ucci.py` conditionals — unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/game.py backend/tests/test_game.py
git commit -m "Add intent and follow-up fields to the move response"
```

---

### Task 5: Frontend — intent block and follow-up block

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/components/ConceptPanel.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `MoveResultResponse.intents` / `.intent_text` / `.follow_up`.
- Produces: `Intent`, `FollowUp` types; the 讲解 card renders 「这步棋的意图」 rows (攻/守/目的) and 「后续变化（引擎）」.

- [ ] **Step 1: Update `types.ts`**

```ts
export interface Intent {
  kind: "attack" | "defend" | "goal";
  text: string;
  piece: string;
  piece_name: string;
  square: string;
  square_chinese: string | null;
  targets: string[];
  targets_chinese: string[];
}

export interface FollowUp {
  moves_uci: string[];
  moves_chinese: (string | null)[];
}
```

In `MoveResultResponse`: remove `move_merit`, add `intent_text: string | null`, `intents: Intent[]`, `follow_up: FollowUp | null`.

- [ ] **Step 2: Update `ConceptPanel.tsx`**

- Change the import to `import type { Intent, MoveResultResponse } from "../api/types";`.
- `summaryOf` strips `[move.why_better, move.intent_text, move.opening_note]` (update its comment).
- Replace the `move_merit` block with:

```tsx
const INTENT_LABELS: Record<Intent["kind"], string> = {
  attack: "攻",
  defend: "守",
  goal: "目的",
};
```

```tsx
{move.intents.length > 0 && (
  <div className="concept__block concept__block--intent">
    <div className="concept__block-title">这步棋的意图</div>
    {move.intents.map((it, i) => (
      <div key={i} className="intent__row">
        <span className={`intent__tag intent__tag--${it.kind}`}>{INTENT_LABELS[it.kind]}</span>
        <span>{it.text}</span>
      </div>
    ))}
  </div>
)}
```

- After it, the follow-up block — hoist `followUp` to a `const` first so TypeScript narrows it inside the callback:

```tsx
const followUp = move.follow_up;
...
{followUp && followUp.moves_uci.length > 0 && (
  <div className="concept__block concept__block--followup">
    <div className="concept__block-title">后续变化（引擎）</div>
    <div className="followup__line">
      {followUp.moves_uci.map((uci, i) => (
        <span key={i}>
          {i > 0 && " → "}
          {i % 2 === 0 ? "对方 " : "你 "}
          {followUp.moves_chinese[i] ?? uci}
        </span>
      ))}
    </div>
  </div>
)}
```

- [ ] **Step 3: Update `index.css`**

Replace `.concept__block--merit` with `.concept__block--intent { background: #eef4ff; border: 1px solid #cdd9f2; }`, add `.concept__block--followup { background: #f7f7f9; border: 1px solid #e3e3e9; }`, `.intent__row { display: flex; gap: 6px; align-items: baseline; margin-top: 3px; }`, `.intent__tag { flex: none; width: 26px; text-align: center; border-radius: 4px; font-size: 11px; font-weight: 600; padding: 1px 0; }`, `.intent__tag--attack { background: #fdecea; color: #b23b2e; }`, `.intent__tag--defend { background: #e8f5ec; color: #2c7a4b; }`, `.intent__tag--goal { background: #eef1f6; color: #4a5b76; }`, `.followup__line { font-size: 12.5px; line-height: 1.9; }`.

- [ ] **Step 4: Typecheck and lint**

Run (from `frontend/`): `npx tsc -b && npx oxlint .`
Expected: no errors.

- [ ] **Step 5: Manual smoke test**

Start the backend (from `backend/`, with `ENGINE_PATH` pointing at `engine/pikafish.exe` on Windows) and `npm run dev` in `frontend/`. Play 炮二平五: the 意图 block shows a 目的 row, 后续变化 shows the engine continuation with 对方/你 labels. Continue into a position with a threat/save to see 攻/守 rows; check the paragraph does not repeat the 意图 text.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/components/ConceptPanel.tsx frontend/src/index.css
git commit -m "Show the intent block and engine follow-up in the panel"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/api-contract.md`
- Modify: `CLAUDE.md` (**untracked** — edit, do not `git add`)

**Interfaces:**
- Consumes: the wire shape from Task 4.
- Produces: contract docs and project notes matching the shipped fields.

- [ ] **Step 1: Update `docs/api-contract.md`**

In the `MoveResultResponse` example replace the `move_merit` line with `intent_text`, an `intents` array (one `attack` row with the full field set; comment `// kind: attack | defend | goal`), and `follow_up` (the four-ply example from Task 4). In the field-notes table replace `move_merit` with three rows: `intents` (facts from the **mover's** view — what the move attacks/saves/is for; shown for every move), `intent_text` (the same facts as one sentence, embedded in `explanation`), `follow_up` (raw engine PV for `side_to_move` after the move, first ply is the opponent; `null` when the game ended or the engine had no line; display-only, never paraphrased). If `explanation`'s example paragraph mentions `move_merit` wording, adjust it.

- [ ] **Step 2: Update `CLAUDE.md`**

Add `intent` to the `analysis/` layer list (`classify · tactics · intent · openings · explain`); extend the coaching-text paragraph: rows come from `analysis/intent.py` (facts) rendered by `explain.py` (wording), the frontend strips `why_better` / `intent_text` / `opening_note` from the paragraph, and adding an intent kind touches the detector, the wording tables in `explain.py`, and the frontend `Intent` type. Leave the file untracked.

- [ ] **Step 3: Commit the contract only**

```bash
git add docs/api-contract.md
git commit -m "Document intent and follow-up fields in the API contract"
```

---

## Self-review notes

- Spec sections are covered: detection → Tasks 1–2; wording/data flow → Task 3; wire (`intents`/`intent_text`/`follow_up`, `move_merit` removal) → Task 4; frontend → Task 5; docs/CLAUDE.md → Task 6; tests distributed per task.
- Rejected-alternative and out-of-scope notes in the spec need no tasks.
- Name consistency: `IntentTag`, `new_attacks`, `saved_pieces`, `detect`, `IntentOut`, `FollowUpOut`, `_follow_up_out`, `FOLLOW_UP_PLIES`, `_goal_fragments`, `_intent_rows` are used with the same names everywhere.
