# Per-move notes and a game library (笔记与对局库) — design

Date: 2026-10-05
Status: approved in brainstorming; pending written-spec review

## Problem

The coach tells the player what the engine thinks of each move. Nothing records
what the *player* thinks. There is also nowhere for a game to live: `GameSession`
is explicitly in-memory ("no persistence or DB"), so closing the tab loses the
game, and a finished game cannot be revisited — engine analysis can be regenerated
on demand, but the user's own reasoning cannot.

Three gaps:

1. No per-move note, and no whole-game note.
2. No game library — nothing survives the tab.
3. No replay file to export, share, or re-import.

## Goals and hard constraints

- **Per-ply notes and one whole-game note**, both editable while playing and
  while browsing history.
- **A game library on disk** that the app browses, opens, renames and deletes.
- **Auto-save**: every mutation (move, undo, redo, note edit) is on disk before
  the next one starts; closing the tab never loses a game.
- **Replay files**: export a game to a JSON file and import it back, notes
  included. An imported game is loadable and continuable.
- **Which plies have notes must be visible at a glance.**

Constraints from the existing project rules:

1. **No LLM, deterministic.** Untouched — this feature adds user-authored text
   only, never generated text.
2. **The engine stays optional.** Nothing in the notes/library path may require
   a running engine; the library must work with the engine down.
3. **Chinese player-facing strings, English code.** Errors surfaced to the user
   are Chinese; identifiers, comments and the record format's keys are English.
4. **No new backend runtime dependencies.** The record format is plain JSON and
   import is a JSON body, not multipart (no `python-multipart`).

## Decisions taken during brainstorming

1. **Storage: backend library + file import/export.** Files live in
   `<repo>/data/games/*.json`; the UI lists them and can also import/export
   files. (Rejected: browser-only download/upload, which loses the browseable
   library.)
2. **Auto-save, not a save button.** The record is written on every mutation.
   A fresh game is created lazily on its first move, so clicking 新对局 repeatedly
   never litters the library with empty games.
3. **An imported game is continuable.** Import copies the file into the library
   and opens it; the player can undo, redo and keep playing from the end. The
   copy is what auto-save updates; the source file on disk is untouched.
4. **Persistence lives inside `GameSession`** (of two proposed routes). The
   session owns the current record id and a `GameStore`; the frontend never
   assembles `start_fen`/`moves`/`notes` itself. Rejected alternative: a
   stateless storage API where the frontend POSTs assembled records — that
   creates two sources of truth (frontend `Timeline` vs backend `move_history`)
   that can drift, and it reinvents the load path anyway.
5. **Undo rewrites the file immediately.** The saved file is the applied line,
   so the file always equals what is on screen. Undone plies remain redoable
   in the page, but the redo branch is not persisted — reopening the record
   shows only the current line. (Rejected: persisting the redo branch, which
   makes the file stop being "the game you are looking at".)
6. **JSON export only**, no human-readable text export. The file must round-trip
   through import; a text rendering is a separate feature and is YAGNI here.
7. **The notes card uses tabs** (「这一步」 / 「整局」) so the game note does not
   push the coaching column taller.

## 1. Record format — `library/records.py`

One JSON object per game:

```json
{
  "format": "xiangqi-shifu-game",
  "version": 1,
  "id": "20261005-1230-a1b2",
  "name": "中炮对屏风马",
  "created_at": "2026-10-05T12:30:00+08:00",
  "updated_at": "2026-10-05T13:02:11+08:00",
  "start_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w",
  "moves": ["h2e2", "h9g7"],
  "notes": ["", "这步进兵太早，应先出车"],
  "game_note": "这套开局我总是吃亏，下次先出车。",
  "result": "ongoing",
  "winner": null
}
```

Rules:

- `notes` is **exactly as long as `moves`**, index-aligned; `""` means no note.
  (Empty string rather than `null`: a JSON textarea value is a string, and it
  keeps the file tidy.) Structural validation rejects a length mismatch.
- `game_note` is the whole-game note; `""` when absent.
- **Engine output is not stored** — no `candidates`, `lines`, `explanation`,
  `intents`, `tactics`. It is large and fully recomputable; opening a move in a
  loaded game re-analyses it. Same reasoning for engine settings (`depth`,
  `multipv`): environment, not record. This is the deliberate trade that keeps
  files small, readable and durable.
- `result` / `winner` are a snapshot written at save time, used for the library
  list (红胜 / 黑胜 / 和棋 / 未完). They are **not trusted on load**: status is
  recomputed from the board, so a hand-edited file cannot fake a result.
- `format` must equal `"xiangqi-shifu-game"` and `version` must be `1`; a
  higher version is refused with 「文件版本过新」 rather than half-read.
- `id` is `YYYYMMDD-HHMMSS-<4 hex>`, minted on creation (sortable, collision
  retried). Import keeps the file's id when free so export→delete→import
  restores the same entry, and mints a new one when taken. `created_at` is
  carried over from the file too — an imported game keeps the date it was
  played, not the date it was imported.
- `start_fen` is stored so non-standard starts survive; a missing/`null`
  `start_fen` means the standard opening position.

## 2. Storage — `library/store.py`

- Directory: `<repo>/data/games/`, overridable with `GAMES_DIR`. Resolved the
  same way `ENGINE_PATH` resolves to `<repo>/engine/pikafish`. Added to
  `.gitignore` (`data/`).
- Files are named `<id>.json` — never the Chinese name, which sidesteps filename
  encoding and sanitisation. Renaming changes `name` inside the file only.
- Writes are atomic: write `<id>.json.tmp`, `os.replace()` onto the target. A
  crash can never leave a half-written record.
- `list()` returns summaries (`id, name, created_at, updated_at, move_count,
  note_count, result, winner`) sorted by `updated_at` descending, skipping and
  logging files that fail to parse rather than failing the whole listing.
- `note_count` = non-empty per-ply notes + (1 if `game_note` else 0).
- Read/write errors raise a store error carrying a Chinese message; the API
  turns it into a 500 and the session keeps its in-memory state intact — a
  failed save must never corrupt the live game.

## 3. Session model — `game.py`

`GameSession.__init__(engine, store=None)`. **`store=None` keeps the session
purely in-memory**, so the existing test suite is untouched and note logic is
testable without disk. Only `routes.py` passes a real store.

New state: `move_notes: list[str]` (parallel to `move_history`), `redo_notes:
list[str]` (parallel to `redo_stack` as a LIFO), `game_note: str`, plus the
current record's `record_id`, `record_name`, `created_at`.

**Notes live and die with their move.** `_undo_one` pops the note onto
`redo_notes`; `_redo_one` pushes it back; `_play_move` clears `redo_notes`
alongside `redo_stack`. A note can therefore never be attached to a different
ply than the one it was written for, and abandoning a branch abandons its notes.

New methods: `set_note(ply, text)` (`ply` 1-based; `None` = whole-game note),
`rename(name)`, `save_as(name)`, `open_record(id)`, `import_record(data)`.

Lifecycle:

- `new_game()` clears the record identity; nothing is written. The first move
  lazily creates a record — default name from the move's `opening_name` when
  the engine supplied one, otherwise `YYYY-MM-DD HH:MM 对局`.
- Every mutation of the line (`_play_move`, `undo`, `redo`, `goto`, `set_note`,
  `rename`) ends by persisting.
- `open_record` / `import_record` replay `start_fen` + `moves` onto a fresh
  board (validating each move's legality; an illegal move raises and leaves the
  previous session untouched), then load notes and identity. **They do not
  persist**, so opening a game does not bump its `updated_at`.
- Deleting the record that is currently open is refused (409). Allowing it
  would make the game reappear under a new id on the next move, which is
  surprising.
- `goto` also persists, for consistency; it stays unexposed to the frontend.

## 4. API — `api/routes.py`, `api/schemas.py`

| Endpoint | Purpose |
|---|---|
| `GET /games` | Library list (`GameSummary[]`), newest first |
| `GET /games/{id}` | Full record (also the export source — the frontend builds the download Blob, so no separate download endpoint) |
| `POST /games/import` | Body = a record. Validate → store (file's id if free) → **open it in the session** → return `PositionResponse` |
| `PATCH /games/{id}` | `{name}`; non-empty, stripped, ≤ 80 chars. Updates the live session's name when it is the current record |
| `DELETE /games/{id}` | 409 when it is the current record |
| `POST /game/save_as` | `{name}` — copy the current line into a new record and switch to it; the original is untouched |
| `POST /game/open` | `{id}` — load into the session, returning `PositionResponse` |
| `PUT /game/note` | `{ply: int \| null, text: str}` — `ply` null = whole-game note. Returns the full `notes` + `game_note` + `saved_at` |

Response additions:

- `PositionResponse` and `MoveResultResponse`: `game_id`, `game_name`,
  `saved_at` (all nullable; null until the first move creates the record) and
  `save_error` (a Chinese message when the last persist failed, else null — the
  mutation still succeeds in memory; `useGame` routes a non-null `save_error`
  into the existing error banner rather than pretending the game was saved).
- `PositionResponse`: `game_note: string` and `notes: string[]` whose length is
  `len(move_history) + len(future_moves)`, ordered applied line first, then the
  redo branch in play order — exactly parallel to the frontend's `Timeline.moves`,
  so the client can replace its array wholesale instead of splicing. Note the
  two `notes` are not the same array: **in the file** it aligns with the applied
  line (`moves`), **in the response** it covers the whole line including the
  redo branch. `Timeline.moves` is the latter.

Errors: unknown id → 404; malformed file / version too new / notes length
mismatch / illegal move in `moves` → 400 with a Chinese `detail`.

**The library endpoints (`GET /games`, `GET /games/{id}`, `PATCH`, `DELETE`) must
not call `_ensure_engine()`** — browsing, renaming, deleting and exporting games
have to work with the engine down. `POST /games/import` and `POST /game/open`
also must not fail on a missing engine: they load the record and leave
`PositionResponse.lines` empty, which the frontend already renders as 引擎不可用.
Playing a move still requires the engine, unchanged.

## 5. Frontend

- `state/useGame.ts`: `Timeline` gains `notes: string[]` parallel to `moves`,
  plus `gameNote`. `recordResult` appends `""`; `recordResult`'s existing
  `slice(0, pointer)` truncation applies to notes too; undo/redo/new/open/import
  replace `notes` and `gameNote` wholesale from the response. Note requests
  carry a sequence number so an out-of-order response cannot overwrite a newer
  one.
- New `components/NotePanel.tsx`, in the coaching column under `ConceptPanel`:
  - Two tabs, 「这一步」 and 「整局」. The header's 「共 N 条」 counts the notes on
    plies; the 整局 tab shows a dot when the game note is non-empty, so the
    count and the dot together say where the writing is.
  - 「这一步」 shows the note for the viewed ply (title: 第 N 步 · 红 马八进七),
    with 「◀ 上一条 / 下一条 ▶」 jumping to the nearest plies that have notes
    (and moving `viewPly`). At ply 0 it shows a hint instead.
  - Textarea saves 500 ms after typing stops, and immediately on blur, tab
    switch or ply switch; a 「保存中 / 已保存 HH:MM」 indicator sits in the corner.
  - Notes are editable for any ply while browsing history — a note belongs to
    its ply, not to where the live board sits.
- New `components/GameLibrary.tsx`, a **modal overlay** opened from Controls.
  Rows: name, date, 步数 · 笔记数, result; actions 打开 · 改名 · 导出 · 删除
  (删除 disabled with a tooltip on the current game). Footer: 「从文件导入」.
  A modal rather than a fourth column because the app is a single non-scrolling
  screen whose `useBoardFit` `RESERVED_W` is a hard-coded column budget; an
  overlay leaves that budget untouched.
- `MoveList` rows get a `✎` marker for plies with a note, with the note text in
  the row's `title`.
- Controls gains the current game name, 另存为, and the saved indicator.
- Import reads the file client-side (`FileReader`) and POSTs JSON; export
  fetches `GET /games/{id}` and downloads a Blob named
  `<sanitised name>.xqsf.json` (sanitised because Chinese game names may contain
  `:` or `/`).
- `api/client.ts` / `api/types.ts` gain the endpoints and `GameRecord` /
  `GameSummary` types.

## 6. Testing

Backend, all with `FakeEngine`, no Pikafish binary, seconds not minutes:

- New `tests/test_library.py`: `GameStore` CRUD on `tmp_path`; atomic write
  leaves no partial file; malformed JSON / wrong `format` / newer `version` /
  `notes` length mismatch are refused with a clear message; ids do not collide;
  a broken file is skipped by `list()` rather than breaking it.
- `tests/test_game.py` extended: notes ride along with undo/redo; a new move
  after undo drops the abandoned branch's notes; `save_as` leaves the original
  intact and switches identity; a malformed record leaves the session unchanged;
  and — the guard that catches coordinate/start-fen mistakes — after
  `open_record`, `move_history_chinese` is character-identical to what was
  rendered when the game was saved (`move_to_chinese` needs the board *before*
  the move, so this is the cheapest end-to-end check of the replay path).
- The 141 existing tests must pass unchanged (store defaults to `None`).

Frontend has no test framework: `npx tsc -b && npx oxlint .`, then a manual pass
of 走几步 → 写笔记 → 悔棋 → 重做（笔记回来了）→ 刷新（库里那局与笔记都在）→
导出 → 删除 → 导入 → 继续走一步 → 另存为.

## 7. Documentation and configuration to update

- `docs/api-contract.md`: the new endpoints, the new response fields, and a
  「对局文件格式」 section describing the record.
- `CLAUDE.md`: `game.py`'s "no persistence" description, the layering diagram
  (a `library/` line under `game.py`), and the notes/record invariants.
- `.gitignore`: `data/`.

## Out of scope

- Human-readable text export (JSON round-trips; text does not).
- Storing engine analysis in the record.
- Tags, folders, full-text search over notes, sharing, multi-user.
- Persisting the redo branch.
- 长捉 / 长兑 (unchanged project scope).
