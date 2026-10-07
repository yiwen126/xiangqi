# 象棋师父 · Xiangqi Shifu — API contract

Base URL: `http://localhost:8000/api`

All player-facing strings are Chinese. All coordinates are UCI-style
(`file a-i` + `rank 0-9`, rank 0 = red's back rank), matching `Move.to_uci()`.

---

## Conventions

### Sides
`"w"` = 红方 (red), `"b"` = 黑方 (black). Red moves first.

### Score perspectives — read this before touching evals

| Field | Perspective | Notes |
|---|---|---|
| `eval_cp` | **RED** | Positive = good for red. Drives the eval bar so it never flips mid-game. |
| `candidates[].score_cp` / `score_mate` | **the MOVER** | Positive = good for whoever was to move in the position *before* the played move. |
| `lines[].score_cp` / `score_mate` | **side to move in the position the lines describe** | Raw engine output; prefer `candidates` for display. |

`score_cp` is in centipawns. `score_mate` is a mate distance in moves (positive =
the side to move mates, negative = gets mated). Exactly one of the two is
non-null per line.

### Chinese notation
Every move is also given in 中文记谱法 (`move_chinese`, `best_move_chinese`,
`pv_chinese`, `move_history_chinese`). Red uses 一二三四五六七八九, black uses
１２３４５６７８９, each counted from its own right. Fields may be `null` only
when the move could not be rendered (a desynchronised engine PV); the frontend
should fall back to the UCI string.

---

## Endpoints

### `GET /health`
```json
{ "status": "ok", "engine_running": true, "engine_path": "/…/engine/pikafish" }
```

### `POST /game/new`
Body: `{ "fen": string | null }` — omit or `null` for the standard start position.
Returns **PositionResponse**.

### `GET /game/position`
Returns **PositionResponse** for the live position.

### `POST /game/move`
Body: `{ "from_sq": "h2", "to_sq": "e2" }`
Returns **MoveResultResponse**. `400` with a Chinese `detail` if the move is illegal.

### `POST /game/engine_move`
No body. The engine plays the side to move. Returns **MoveResultResponse**.

### `POST /game/undo`
Body: `{ "plies": int }` — **optional**, defaults to `1`. Body may be omitted entirely.
Returns **PositionResponse**. `400` if more plies are requested than have been played.

> Multi-ply matters: in an engine game a single undo lands on the engine's turn,
> which the frontend would immediately replay. Step back **2** plies to reach the
> player's own turn.

### `POST /game/redo`
Body: `{ "plies": int }` — optional, defaults to `1`. Returns **PositionResponse**.

### `POST /game/goto`
Body: `{ "ply": int }` — `0` = starting position. Returns **PositionResponse**.

> This **mutates the live game**. Browsing history for display should be done
> client-side from cached move results; calling `goto` on the server lets the
> engine's auto-move fire from the position you navigated to.

### `POST /game/save_as`
Body: `{ "name": string }` — 另存为：copy the current line into a fresh library
entry, leaving the original file alone. The session switches to the new record.
Returns **PositionResponse**. The name is stripped and capped like `PATCH`
(`"名字不能为空"` / `"名字太长了"`). `400` when there is nothing to save yet:
`"还没有走子，无法另存为"`.

### `PUT /game/note`
Body: `{ "ply": int | null, "text": string }` — write a note on a single ply or
on the whole game. `ply` is 1-based over the **whole line** (`move_history` +
`future_moves`); `null` writes the whole-game note. Returns **NoteResponse**.
`400` `"无效的步数：9"` when `ply` is beyond the whole line.

### `POST /game/open`
Body: `{ "id": string }` — 打开对局：replay a saved game into the live session
and return its whole line. Returns **LoadedGameResponse**. `404` when the game
is not in the library (`库里没有这局`) or the id is unusable
(`对局编号不合法`); `400` for an unreadable file or a line that fails to replay
(`第 N 步着法不合法：a0b1`). Opening never writes, so it does **not** bump the
game's `updated_at` (the library sorts on it). The session adopts the id the
game was **opened by** (the file name), not the `id` written inside the file:
opening a hand-renamed file re-labels it by its file name on the next save (the
in-file `id` is normalised).

### `GET /games`
Returns a JSON array of **GameSummary**, newest first. `[]` when empty.

### `GET /games/{game_id}`
Returns the game as a **GameRecord** (see 「对局文件格式」). This is the export
endpoint, but the object is **normalised, not byte-raw**: the file is read
through `GameRecord.parse`, so unknown keys are dropped, `format`/`version` are
rewritten to the canonical values and a blank `name` becomes `无名对局`. Keys
added by hand do **not** survive an export/import round trip. `404` / `400` as
for `open`.

### `POST /games/import`
Body: the **raw 对局文件 object** (not a wrapper). It is validated by
`GameRecord.parse`, so all structural rules apply and each failure is a `400`
with the specific Chinese `detail` (see 「对局文件格式」). A body that is not a
JSON object is a `422`. Returns **LoadedGameResponse** for the imported game;
the line is saved as a new library entry, keeping the file's id when it is free
and minting one when the library already uses it.

### `PATCH /games/{game_id}`
Body: `{ "name": string }` — 重命名. The name is stripped; `400`
`"名字不能为空"` when blank, `400` `"名字太长了"` when longer than 80
characters. Works on any saved game, not only the open one; when it *is* the
open game the live session's `game_name` is updated too. Returns
**GameSummary**.

### `DELETE /games/{game_id}`
Returns `{ "deleted": "<game_id>" }`. `409` `"这是当前对局，请先开新对局"`
when the id is the game currently open in the session — its file is being
auto-saved into, so deleting it would silently drop the game in progress.
Deleting an id that is not there succeeds as a no-op.

> Everything under `/games` plus `open`, `save_as` and `note` works with the
> engine down — browsing, renaming, deleting, exporting, note editing, opening
> and importing. Their responses then carry `"lines": []` and the frontend
> shows 引擎不可用. The remaining `/game` endpoints still answer `503` without
> an engine.

---

## PositionResponse

```jsonc
{
  "fen": "rnbakabnr/9/1c5c1/… w - - 0 1",
  "side_to_move": "w",
  "game_status": "ongoing",
  "in_check": false,
  "winner": null,
  "result_note": null,
  "move_history": ["h2e2", "h9g7"],
  "move_history_chinese": ["炮二平五", "马８进７"],
  "future_moves": ["h0g2"],
  "notes": ["", "这步太急", "这步被悔了，笔记还留着"],
  "game_note": "这套开局我总是吃亏。",
  "game_id": "20261005-1230-a1b2",
  "game_name": "中炮对屏风马",
  "saved_at": "2026-10-05T22:56:22+08:00",
  "save_error": null,
  "lines": [ { "multipv": 1, "score_cp": 24, "score_mate": null, "pv": ["g3g4", …] } ]
}
```

* `future_moves` — moves undone and available to redo, in replay order.
* `notes` — one entry per ply of the **whole line**, parallel to
  `move_history + future_moves`: the applied moves first, then the undone ones
  in play order. `""` means "no note on this ply". Note the third entry here
  belongs to `future_moves[0]` — a note on an undone ply is still reported (see
  「对局文件格式」 for why the file is different).
* `game_note` — the note on the game as a whole (`""` when none).
* `game_id` / `game_name` — the 对局库 identity of the game in flight. Both are
  `null` until the first move auto-creates the record, and after 新对局; they
  fill in on the first move that gets saved, or immediately on open/import.
* `saved_at` — when the record was last written (ISO 8601, local offset).
  `null` before the first save, or when auto-save is not available.
* `save_error` — non-null when the last auto-save failed (e.g. a read-only
  disk). The move still stands and play continues from memory: 自动保存 must
  never cost the player a move. The frontend shows this and keeps going.
* `lines` — empty when the game is over or the engine is unavailable.

---

## MoveResultResponse

```jsonc
{
  "fen": "…",
  "side_to_move": "b",
  "move_uci": "h2e2",
  "move_chinese": "炮二平五",
  "played_matches_best": false,
  "best_move_uci": "c3c4",
  "best_move_chinese": "兵七进一",
  "label": "优秀",
  "label_en": "Excellent",
  "color": "#5cb85c",
  "cp_loss": 3,
  "eval_cp": 24,

  "candidates": [
    {
      "rank": 1,
      "move_uci": "c3c4",
      "move_chinese": "兵七进一",
      "score_cp": 24,
      "score_mate": null,
      "pv_uci":     ["c3c4", "i9h9", "h0g2", "h7i7"],
      "pv_chinese": ["兵七进一", "车９平８", "马二进三", "炮８平９"],
      "is_played": false
    }
    // …up to 3, rank 1 = engine's first choice
  ],

  "why_better": "引擎首选 兵七进一：…",
  "intent_text": "这步意在威胁白吃对方的４路马（d4）。",
  "intents": [
    {
      "kind": "attack", // attack | defend | goal
      "text": "威胁白吃对方的４路马（d4）",
      "piece": "R",
      "piece_name": "车",
      "square": "d5",
      "square_chinese": "六路车（d5）",
      "targets": ["d4"],
      "targets_chinese": ["４路马（d4）"]
    }
  ],
  "follow_up": {
    "moves_uci": ["h9g7", "h0g2", "b9c7", "c3c4"],
    "moves_chinese": ["马８进７", "马二进三", "马２进３", "兵七进一"]
  },
  "passing_plan": {
    "moves_uci": [
      "e2e6", "b2e2", "e6e4", "h0g2", "i0h0", "h0h7", "h7b7", "a0a1", "a1f1", "f1f8"
    ],
    "moves_chinese": [
      "炮五进四", "炮八平五", "前炮退二", "马二进三", "车一平二",
      "车二进七", "车二平八", "车九进一", "车九平四", "车四进七"
    ]
  },
  "best_passing_plan": {
    "moves_uci": [
      "h2e2", "e2e6", "b2e2", "e6e5", "b0c2", "a0b0", "b0b7", "b7h7", "i0i1", "i1f1"
    ],
    "moves_chinese": [
      "炮二平五", "炮五进四", "炮八平五", "前炮退一", "马八进七",
      "车九平八", "车八进七", "车八平二", "车一进一", "车一平四"
    ]
  },

  "explanation": "炮二平五，优秀（较最佳着法损失约 3 分）。…",

  "tactics": [
    {
      "kind": "hanging",
      "side": "b",
      "piece": "R",
      "piece_name": "车",
      "square": "a0",
      "square_chinese": "九路车（a0）",
      "targets": ["a1"],
      "targets_chinese": ["１路车（a1）"]
    }
  ],

  "opening_name": "中炮局",
  "opening_note": "炮二平五。红方右炮平中…",
  "in_book": true,
  "left_book_now": false,

  "game_status": "ongoing",
  "result_note": null,
  "in_check": false,
  "winner": null,

  "game_id": "20261005-1230-a1b2",
  "game_name": "中炮对屏风马",
  "saved_at": "2026-10-05T22:56:22+08:00",
  "save_error": null
}
```

### Field notes

| Field | Meaning |
|---|---|
| `label` | 最佳 / 优秀 / 好棋 / 不太准确 / 失误 / 大漏着 |
| `color` | Hex colour for the label badge |
| `cp_loss` | Centipawns lost vs. the engine's best. Always `0` for a game-ending move. |
| `candidates` | Top engine choices **for the position before this move**. `rank` 1 is best. Empty if the engine was unavailable. |
| `why_better` | Why the engine's pick beats what was played. `null` when the move matched the engine or `cp_loss` is 0 — nothing is "better" than an equally-rated move. |
| `intents` | Facts from the **mover's** view: what the move attacks, saves, or is for. Shown for every move — empty when the move ended the game, or when the move carried no reportable intent facts. |
| `intent_text` | The same facts as one sentence, embedded verbatim in `explanation`. |
| `follow_up` | Raw engine PV for `side_to_move` **after** the move — the first ply is the opponent. `null` when the game ended or the engine had no line. Display-only, never paraphrased. |
| `passing_plan` | Up to ten consecutive moves for the **mover** in the hypothetical where the opponent keeps passing (chained side-flipped "null move" positions): "若对方不应，…". Raw engine output, display-only. The line stops at (and includes) a move that gives check — passing out of check is not a legal hypothetical. `null` when the played move gave check, the game ended, or the engine had no line. |
| `best_passing_plan` | The same opponent-keeps-passing line for the engine's preferred move (the better choice shown in `best_move_chinese`). `null` when there is no better choice to show (played move matched the engine, or `cp_loss` is 0) or under the same check/no-line conditions. |
| `explanation` | The full coaching paragraph. Single line, already embeds the verdict, `why_better`, and `intent_text`. |
| `tactics` | Problems the **mover** now faces. `side` is the side the tactic favours. |
| `left_book_now` | `true` **only** on the exact ply that diverged from theory — do not treat as sticky state. |
| `lines` | Raw engine lines for the position **after** the move. |
| `game_id` / `game_name` / `saved_at` / `save_error` | The same auto-save identity fields as `PositionResponse` — this move has just been mirrored into the record (or its save failed and is reported in `save_error`). |

### `game_status`

| Value | Meaning | `winner` |
|---|---|---|
| `ongoing` | Game continues | `null` |
| `checkmate` | 将死 | winning side |
| `stalemate` | 困毙 — a **loss** in Xiangqi, not a draw | winning side |
| `draw_repetition` | 和棋 by repetition | `null` |
| `perpetual_loss` | 长将判负 — perpetual check loses | side that was *not* checking |

`result_note` carries the Chinese sentence describing the result, e.g.
`"红方长将，按中国象棋规则判负，黑方胜。"` It is `null` while `ongoing`.

> 长捉 (perpetual chasing) and 长兑 are **not** implemented; such games are
> reported as `draw_repetition`. See the README.

---

## LoadedGameResponse

`PositionResponse` plus the whole saved line. **Only** `POST /game/open` and
`POST /games/import` return it; undo/redo/new after opening answer with the
lean `PositionResponse`.

```jsonc
{
  // …every PositionResponse field…
  "plies": [
    {
      "move_uci": "h2e2",
      "move_chinese": "炮二平五",
      "fen": "rnbakabnr/9/1c5c1/… b - - 1 1",
      "side_to_move": "b"
    },
    {
      "move_uci": "h9g7",
      "move_chinese": "马８进７",
      "fen": "rnbakab1r/9/1c4nc1/… w - - 2 2",
      "side_to_move": "w"
    }
  ]
}
```

* `plies` covers the **applied line only** (`move_history`); a game loaded from
  disk has no redo branch.
* Each `fen` is the position **after** that ply, and `side_to_move` is the side
  to move **after** it — the same convention as `MoveResultResponse`, so the
  frontend can step through an opened game without replaying the moves itself
  (`board/fen.ts` only parses for rendering, it does not apply moves).

---

## NoteResponse

```json
{
  "notes": ["这步好", "这步太急"],
  "game_note": "整局笔记",
  "saved_at": "2026-10-05T22:56:28+08:00",
  "save_error": null
}
```

The note line as it stands after the write, with the same alignment as
`PositionResponse.notes`. No position and no engine output: a note changes
neither.

---

## GameSummary

The library-list row — enough to render the list without loading a game.

```json
{
  "id": "20261005-1230-a1b2",
  "name": "中炮对屏风马",
  "created_at": "2026-10-05T12:30:00+08:00",
  "updated_at": "2026-10-05T13:02:11+08:00",
  "move_count": 2,
  "note_count": 2,
  "result": "ongoing",
  "winner": null
}
```

* `move_count` counts the applied line's moves.
* `note_count` counts the non-blank ply notes **plus 1** when `game_note` is
  non-blank.
* The list is sorted by `updated_at`, then `id`, newest first.
* One unreadable file is skipped (and logged server-side) rather than failing
  the whole list.

---

## 对局文件格式

The library is a directory of plain JSON files, one per game:
`<repo>/data/games/<id>.json` (override with `GAMES_DIR`). `GET /games/{id}`
returns this object **normalised** — the file is read back through
`GameRecord.parse`, so unknown keys are dropped rather than echoed — and
`POST /games/import` accepts it, so a game can be exported, edited on disk, and
imported back. All strings are UTF-8; non-ASCII is written unescaped.

```json
{
  "format": "xiangqi-shifu-game",
  "version": 1,
  "id": "20261005-1230-a1b2",
  "name": "中炮对屏风马",
  "created_at": "2026-10-05T12:30:00+08:00",
  "updated_at": "2026-10-05T13:02:11+08:00",
  "start_fen": null,
  "moves": ["h2e2", "h9g7"],
  "notes": ["", "这步太急"],
  "game_note": "这套开局我总是吃亏。",
  "result": "ongoing",
  "winner": null
}
```

| Field | Rule |
|---|---|
| `format` | Must be `"xiangqi-shifu-game"`; anything else is `400` `"不是象棋师父的复盘文件"`. |
| `version` | `1` today. A newer version is `400` `"文件版本过新（v2）"`; `< 1` is `"文件版本不合法"`. |
| `id` | `[0-9A-Za-z-]` only. An unusable id is not fatal: `import` mints a fresh one (`对局编号不合法` only guards path building). |
| `name` | Blank is normalised to `"无名对局"`, not rejected — a nameless game is a valid game. |
| `created_at` / `updated_at` | ISO 8601 with the local UTC offset, seconds precision. `updated_at` is rewritten by the store on every save. |
| `start_fen` | `null` = standard start position. Otherwise it must parse (`"起始局面不合法"`). |
| `moves` | UCI strings, in play order. Each must round-trip (`Move.from_uci`) **and** be legal in the position it is played in — replay is a board operation the server does, not the frontend (`"第 N 步着法不合法：a0b1"`). |
| `notes` | Parallel to `moves`; `len(notes)` **must equal** `len(moves)` (`"笔记数量与着法不一致（1 ≠ 2）"`). A missing key reads as empty. |
| `game_note` | The whole-game note; `""` when none. Never counted against `notes`. |
| `result` | One of `ongoing`, `checkmate`, `stalemate`, `draw_repetition`, `perpetual_loss` (`"未知的终局状态"`). A snapshot from the last save, not a rule the replay re-derives. |
| `winner` | `"w"`, `"b"` or `null`. |
| unknown keys | Ignored on import — a file may carry extra metadata without becoming unreadable. |
| any other missing / wrongly-typed field | `400` `"文件字段不完整或格式不对"` — e.g. a missing or non-string `id` / `created_at` / `updated_at`, or a body that is not a JSON object at all. Every malformed file raises one of the Chinese errors above, so a single bad file can never take the library down. |

### No engine output is stored

A record holds **only the player's own game**. Engine evals, candidates, PVs
and coaching text are deliberately absent: they are large, they are fully
recomputable from the moves, and a file that embedded them would go stale the
moment the engine, its version or `ENGINE_DEPTH` changed. A loaded game
therefore has `"lines": []` until the engine analyses the current position
again; with the engine down the frontend shows 引擎不可用 and the game still
opens, replays and edits normally.

### Why `notes` in a response covers the redo branch, and a file's does not

`PositionResponse.notes` is parallel to `move_history + future_moves` — the
whole line, including plies that are currently undone. A note written on an
undone ply (`PUT /game/note` accepts it) rides back into place on 重做 and dies
with the branch if a new move discards it; the session keeps the notes in the
same LIFO as `redo_stack` precisely so a note can never drift to a different
ply.

The file has no redo stack: `moves` is always the **applied** line, and `notes`
must match it exactly. So a note on an undone ply exists in memory (and in
responses) but not yet on disk — it is written when the ply is redone, and
discarded if the branch is. That is why a response's `notes` can be longer than
the saved file's, and why notes must always be aligned to the move list they
travel with, never to a single position.

---

## Errors

Every error body is `{ "detail": "<Chinese sentence>" }`.

`400` — an illegal move, an out-of-range undo/redo/goto (`"不合规则的走法：a0i9"`,
`"无效的步数：9"`), an unusable name (`"名字不能为空"`, `"名字太长了"`), an
unusable replay file (`"不是象棋师父的复盘文件"`, `"笔记数量与着法不一致（1 ≠ 2）"`,
`"第 N 步着法不合法：a0b1"`), or an unusable id on `DELETE`
(`"对局编号不合法"`).

`404` — the game is not in the library: `{ "detail": "库里没有这局" }`, or an
id the store cannot use on `GET /games/{id}` / `POST /game/open`:
`{ "detail": "对局编号不合法" }`.

`409` — trying to delete the game currently open in the session:
```json
{ "detail": "这是当前对局，请先开新对局" }
```

`422` — FastAPI's own validation error, e.g. a body that is not a JSON object
where an object is required (`POST /games/import`, `PATCH /games/{id}`).

`503` — engine missing. `detail` includes the setup instruction:
```json
{ "detail": "引擎不可用（Engine not available）: … 请运行 scripts/setup_engine.sh …" }
```
The server still starts without an engine so the UI can render and show this,
and the whole library keeps working without it (see the endpoint notes above).

---

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `ENGINE_PATH` | `<repo>/engine/pikafish` | Engine binary location |
| `ENGINE_DEPTH` | `14` | Search depth per analysis |
| `ENGINE_MULTIPV` | `3` | Number of candidate moves returned |
| `GAMES_DIR` | `<repo>/data/games` | 对局库 directory — one `<id>.json` per saved game (see 「对局文件格式」) |
