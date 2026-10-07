# Move-intent explanations (这步棋的意图) — design

Date: 2026-10-05
Status: approved in brainstorming; pending written-spec review

## Problem

The coaching text answers "how good was this move?" (`label`, `cp_loss`,
`why_better`) and, partly, "what did it do?" (`move_merit`: check / capture /
development / mobility). It never says what the move is **for**: which enemy
piece it attacks, which of our pieces it defends, which concrete enemy threat
it answers, or how the position is expected to continue. `tactics` only
reports problems the mover *now faces* — the attacking side of the board is
invisible in the payload.

## Goals and hard constraints

Add a deterministic "intent" layer to each played move and surface it in the
讲解 card:

- 攻 — enemy pieces this move newly attacks or threatens (winning threats and
  pressure/exchange contacts, worded differently).
- 守 — own pieces saved from a real loss, with the opponent's concrete
  threatening move named in 记谱法; plus "escaped" when the moved piece itself
  was under a winning attack.
- 目的 — the positional facts the old `move_merit` already carried.
- 后续变化 — the engine's expected continuation after the move, displayed as
  data (not paraphrased into claims).

Constraints (non-negotiable, from project rules):

1. **No LLM anywhere.** Prose is assembled from board facts and raw engine
   output in `analysis/explain.py`.
2. **No speculative claims.** Everything stated as fact comes from exact board
   analysis (`SEE`, attacker enumeration) or is raw engine data. The engine PV
   is never turned into "the opponent plans X" narration.
3. **Deterministic.** Same board (+ same engine build for the PV display) ⇒
   same output.
4. **No extra engine searches.** The before-lines are already cached and the
   after-lines are already computed by `_play_move`; intent detection is pure
   board analysis.

## Decisions taken during brainstorming

1. "应对对方后续" means **both**: (a) concrete threats the move resolves —
   static, verifiable, opponent's move named in notation; and (b) the engine's
   expected continuation after the move — display-only data.
2. Attack scope includes **pressure / exchange offers**, not only winning
   threats: defended pieces worth ≥ 马 get 施压/邀兑 wording, never 威胁
   wording. Still only *changes this move caused*; pre-existing board contact
   is never re-announced.
3. Presentation: the existing 「这步棋的作用」 block becomes 「这步棋的意图」
   with 攻/守/目的 rows; a second block 「后续变化（引擎）」 shows the after-PV.
   `move_merit` is removed from the wire contract and replaced by structured
   fields.
4. Implementation route: new pure module `analysis/intent.py` (route 1 of 3);
   the alternatives (extending `tactics.py`'s `TacticTag`, or driving
   everything from PV diffs) were rejected — the former muddies the `tactics`
   field's "problems the mover faces" semantics, the latter is unverifiable
   narration that is brittle across Pikafish builds.
5. Intents are shown for **all** moves, including mistakes and blunders.
   Wording stays strictly factual; praise-flavored fallbacks are suppressed
   for non-good moves. The verdict remains with `label` + `why_better`.

## 1. Detection — `backend/app/analysis/intent.py` (new)

Pure module: no engine, no I/O, no notation. Input `board_before` + `move`
(clones `board_after` internally), output `list[IntentTag]`. It renders
nothing; `explain.py` owns all wording, exactly as `tactics.py` → `explain.py`
today.

Prerequisite: promote `tactics._capture_is_legal` → `capture_is_legal` and
`tactics._defenders` → `defenders_of`, updating their internal uses;
`intent.py` imports `attackers_of`, `capture_is_legal`, `defenders_of`,
`static_exchange_eval`, `piece_value`, `SEE_REPORT_THRESHOLD` from
`tactics`.

```python
@dataclass
class IntentTag:
    kind: str                    # "attack" | "defend"
    piece: str                   # mover-side piece letter
    piece_sq: tuple[int, int]
    target_sqs: list[tuple[int, int]]
    detail: dict
```

Constants (module level, tunable):

```python
ATTACK_EVEN_MIN_VALUE = 4.0   # even/pressure tier only for victims >= 马
DEFEND_MIN_VALUE = 2.0        # saving a pawn is never reported
MAX_ATTACK_ROWS = 2
MAX_DEFEND_ROWS = 2
```

### 1.1 Attacks

One tag per **victim** (not per attacker–victim pair), so a victim is never
reported twice:

- Scan every enemy piece V (skip generals) on both boards: legal attackers
  (`attackers_of` + `capture_is_legal`, so pinned attackers don't count) and
  `see_after = static_exchange_eval(after, V, mover)`,
  `see_before = ...(before, V, mover)`.
- **Trigger** (either): V had no legal attacker before **and** has one after
  (new contact); or `see_before < SEE_REPORT_THRESHOLD ≤ see_after` (newly
  winnable regardless of contact age).
- **Tier**: `win` when `see_after ≥ SEE_REPORT_THRESHOLD`; otherwise `even`
  when `0 ≤ see_after < SEE_REPORT_THRESHOLD`, the victim value is ≥
  `ATTACK_EVEN_MIN_VALUE`, **and** the victim is worth at least as much as the
  attacking piece. (`static_exchange_eval` bottoms out at 0 — a capture that
  loses material already reads as 0 and the side simply declines; the value
  condition additionally keeps a mere standoff, e.g. a chariot poking a
  defended horse, out of the report.)
- Attacker attribution: the moved piece if it is among the new legal
  attackers of V, else the smallest-value new legal attacker. `piece_sq` is
  the attacker's square on the **after** board.
- detail: `{"tier": "win"|"even", "see": float, "defended": bool}`.
- Victim already captured by the move does not exist on the after board and is
  therefore never reported.
- Pre-existing winnable threats (`see_before ≥ threshold`) are never this
  move's doing — skipped. The old `_build_merit` branch that reported a newly
  threatened piece used the attacker's square as the target (stated "建立了对
  {attacker}的威胁"); it is deleted, and a regression test pins the victim
  naming.

### 1.2 Defenses and escapes

For each own piece P (skip generals, value ≥ `DEFEND_MIN_VALUE`) that is
losable before — `see_before = static_exchange_eval(before, P, by opponent) ≥
SEE_REPORT_THRESHOLD`:

- P is the moved piece (P's square is `move.from_sq`): **escape** when it is
  no longer losable at its destination (`see_after(to_sq) < threshold`).
  `piece_sq = move.from_sq` (rendered against `board_before`), `detail.escape
  = True`.
- P did not move: **defend** when `see_after(P) < threshold`.
  `piece_sq = P` (same square on both boards).
- Still losable after (`see_after ≥ threshold`, even if the loss shrank) ⇒ no
  tag; the problems section covers it.

Every tag names the concrete threat: `detail.threat_uci` is the move
`primary attacker → victim` computed on `board_before`, where the primary
attacker is the smallest-value legal attacker (the one SEE would use).
`target_sqs = [primary attacker's square]`, `detail.see_before = float`.

### 1.3 Output

`detect(board_before, move) -> list[IntentTag]`: attacks first (`win` rows
before `even` rows, then by victim value descending), capped at
`MAX_ATTACK_ROWS`; then defends (by `see_before` descending), capped at
`MAX_DEFEND_ROWS`. Deterministic ordering; identical inputs give identical
output.

Note: 空头炮 keeps its existing dedicated wording. It is not a piece attack
(the general is excluded from victims), so `explain.py` still builds that row
from the existing `new_gains` hollow-cannon detection — no overlap.

## 2. Wording and data flow

### 2.1 Wording templates (`explain.py`, first-pass — constants centralized for tuning)

| Case | Template (examples verbatim) |
|---|---|
| attack / `win` / victim undefended | `威胁白吃对方的{describe_piece(target)}` — e.g. 威胁白吃对方的４路马（d4） |
| attack / `win` / victim defended | `威胁吃对方的{Ｘ}，兑子后你净赚约 {see} 兵` |
| attack / `even` / `see == 0` | `邀兑对方的{Ｘ}，对方有子保护` |
| attack / `even` / `0 < see` | `先手瞄住对方的{Ｘ}，兑子你稍占便宜` |
| ≥2 `win` victims, same attacker | merged into one row: `形成双重攻击：对方的{Ａ}和{Ｂ}无法同时兼顾` (victims in `targets`) |
| hollow cannon (from `new_gains`) | existing: `架起空头炮，直指对方中路` |
| defend | `保住{七路马（c4）}，化解对方{车８进４}吃{马}的威胁` — the threat move rendered with `move_to_chinese(board_before, threat_uci)` |
| escape | `把受攻的{七路马（c4）}从对方攻击下走开` (rendered against `board_before`) |

Pawn-unit numbers are printed by a small helper that drops a trailing `.0`
(2 rather than 2.0); existing tactic sentences are left untouched.

`describe_piece` board choice per row: attacks → `board_after` (attacker and
victim squares); defends → `board_before` (the saved piece is described at
its unchanged square, and the threatener must be read from the before board —
the move may have captured it); escapes → `board_before`; goals →
`board_after`.

### 2.2 Goal rows

`_build_merit` is reduced to a fragment builder over the existing
`_move_facts` positional facts (check / capture / develops / crossed river /
centre file / mobility gains / in-book opening), joined with 、 into one
`goal` row. Tactical branches that the new attack/defend rows supersede are
deleted.

- Good moves keep the existing cascade including the 稳健的调整 fallback and
  the in-book phrasing — but both are suppressed when attack/defend rows
  exist (they are filler next to a real threat).
- Non-good moves (`cp_loss > 40`) keep only the action facts (check / capture
  / develop / crossed river / centre / mobility) and drop the
  quality/book-flavored phrasings ("是一步稳健的调整…", "价值在于改善子力位置",
  "稳稳走在「…」的主流路线上"); if nothing remains, no goal row is emitted.
  Intents are still shown.

### 2.3 Paragraph composition

`build_explanation` sentence order becomes: verdict → `intent_text` →
problems → `why_better` → opening → repetition.

`intent_text` is one sentence built from the fragment list in row order:
`"这步意在" + "；".join(fragments) + "。"`; fragments are the row texts
verbatim (coordinates included), goal fragments already joined with 、.
Example: 这步意在威胁白吃对方的４路马（d4）；保住七路马（c4），化解对方车８
进４吃马的威胁；出动大子、活通车路。 Still a single non-empty line (no
newlines). `None` when there are no fragments.

Terminal moves (checkmate / stalemate / repetition endings): `intents = []`,
`intent_text = None`; the terminal sentence dominates, block hidden.

### 2.4 Wire changes (`schemas.py`, `game.py`)

`MoveResultResponse`:

- **remove** `move_merit`
- **add** `intent_text: str | None` — the verbatim sentence embedded in
  `explanation` (the frontend strips it)
- **add** `intents: IntentOut[]`:

```jsonc
{
  "kind": "attack",                  // attack | defend | goal
  "text": "威胁白吃对方的４路马（d4）",
  "piece": "R", "piece_name": "车",
  "square": "b2", "square_chinese": "八路车（b2）",
  "targets": ["d4"], "targets_chinese": ["４路马（d4）"]
}
```

  Row shapes: attack → `piece/square` = our attacker (after board), `targets`
  = victim(s); defend → `piece/square` = our saved piece, `targets` =
  primary threatener; goal → `piece/square` = moved piece at its destination,
  `targets = []`. v1 frontend renders only `kind` + `text`; the squares are in
  the contract for future board highlighting.

- **add** `follow_up: FollowUpOut | None`:

```jsonc
{ "moves_uci": ["h9g7", "h0g2", "b9c7", "c3c4"],
  "moves_chinese": ["马８进７", "马二进三", "马２进３", "兵七进一"] }
```

  Source: `lines_after[0].pv` truncated to `FOLLOW_UP_PLIES = 4` (new
  constant in `game.py`), rendered with the existing
  `moves_to_chinese(board_after, pv)`; `moves_chinese` is padded to the same
  length with `null` where a move cannot be rendered. `None` when the game
  ended on this move or no lines exist. The PV starts with the side to move
  **after** the move, i.e. the opponent; the frontend labels plies
  alternately 对方 / 你 starting with 对方.

`PositionResponse` and `tactics` are unchanged. `docs/api-contract.md` is
updated alongside: example payloads, the field table, the perspective note
(`follow_up` is raw engine output for `side_to_move`), and the removal of
`move_merit`.

## 3. Frontend

`api/types.ts`: add `Intent` and `FollowUp`; in `MoveResultResponse` replace
`move_merit` with `intent_text`, `intents`, `follow_up`.

`components/ConceptPanel.tsx`:

- `summaryOf` strips `[why_better, intent_text, opening_note]` instead of
  `move_merit`.
- New block 「这步棋的意图」 rendered when `intents.length > 0`, rows in wire
  order with a small chip per kind: `attack` → 攻, `defend` → 守, `goal` →
  目的.
- New block 「后续变化（引擎）」 rendered when `follow_up` is non-null:
  `对方 {moves_chinese[0] ?? moves_uci[0]} → 你 {…} → 对方 …`, alternating.
- The block is informational; no quality gate (per decision 5).

`index.css`: replace `.concept__block--merit` with `.concept__block--intent`;
add `.intent__row`, `.intent__tag--attack|--defend|--goal`, and
`.followup__line`. `useBoardFit`'s `RESERVED_W`/`RESERVED_H` do not change —
column widths are untouched and the teach column already scrolls
(`layout__scroll`).

## 4. Tests

`backend/tests/test_intent.py` (new, FEN fixtures, no engine):

- attack tiers: newly winnable undefended piece (`win`); new contact on a
  defended piece with SEE 0 (`even`) and 0 < SEE < 1.5; attacker pinned /
  capture illegal ⇒ no tag; discovered attack attributed to the freed piece;
  pre-existing attack not re-reported; negative SEE not reported; victims
  below `ATTACK_EVEN_MIN_VALUE` skipped in the `even` tier; two win victims
  from one attacker both emitted (renderer merges); generals never targeted.
- defenses: piece losable before and safe after ⇒ tag with the exact
  `threat_uci` and primary attacker; attacker captured ⇒ still reported once;
  still-losable ⇒ no tag; mover escaping an attack ⇒ `escape` tag rendered
  against `board_before`; pieces below `DEFEND_MIN_VALUE` skipped.
- caps and ordering; determinism (two calls, same output).

`backend/tests/test_explain.py`:

- `intent_text` is embedded verbatim in `explanation` and the paragraph
  remains a single line.
- Wording tiers pinned (威胁白吃 / 兑子后你净赚 / 邀兑 / 瞄住 / 保住…化解 /
  走开).
- Blunders still get intents, with no 稳健的调整 fallback and no praise.
- Regression: a move that newly threatens a hanging victim names the
  **victim**, not the attacker (the deleted `_build_merit` bug).
- Terminal moves: `intents == []`, `intent_text is None`.

`backend/tests/test_game.py`:

- `move_merit` gone; `intents` / `intent_text` present.
- `follow_up` from FakeEngine lines: truncated to 4, Chinese rendered,
  `null` padding on desync, `None` on terminal moves and when no lines.

Frontend: `npx tsc -b && npx oxlint .`; manual pass over a few positions in
the dev server (opening quiet move, a threat, a save, a blunder, a mate).

Docs: `docs/api-contract.md` (contract update) and `CLAUDE.md` (add
`intent.py` to the layering list; add a "adding an intent kind touches these
places" note mirroring the tactics note; update the ConceptPanel strip-list
description).

## Files touched

- `backend/app/analysis/intent.py` — new
- `backend/app/analysis/tactics.py` — promote `capture_is_legal`
- `backend/app/analysis/explain.py`
- `backend/app/game.py`, `backend/app/api/schemas.py`
- `backend/tests/test_intent.py` — new; `test_explain.py`, `test_game.py`
- `frontend/src/api/types.ts`, `components/ConceptPanel.tsx`, `index.css`
- `docs/api-contract.md`, `CLAUDE.md`

## Out of scope

- PV-diff claims ("this move stops the opponent's plan"); mate/king-safety
  threat narration; intents for engine candidates (`candidates[]`); board
  highlighting (squares are carried for it, nothing consumes them yet);
  长捉 / 长兑; any LLM.

## Tunables (centralized, first-pass values)

- `ATTACK_EVEN_MIN_VALUE = 4.0`, `DEFEND_MIN_VALUE = 2.0`,
  `MAX_ATTACK_ROWS = 2`, `MAX_DEFEND_ROWS = 2`, `FOLLOW_UP_PLIES = 4`.
- Even-tier wording (邀兑 vs 瞄住) and the `意在` sentence template; tests pin
  the current examples so changes are deliberate.
