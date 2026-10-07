# Per-move notes and a game library (笔记与对局库) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every move and every game a place for the player's own notes, an on-disk game library that auto-saves, and a JSON replay file that carries the notes through export and import.

**Architecture:** A new pure-ish `backend/app/library/` layer (record model + file store) sits under `game.py`. `GameSession` gains two note stacks that mirror the existing `move_history`/`redo_stack` pair, plus a record identity and a `_persist()` that writes the applied line after every mutation. Eight new endpoints expose the library and note editing; the frontend adds a tabbed notes card to the coaching column and a library modal.

**Tech Stack:** Python 3.13 / FastAPI / pydantic v2 (backend); React 18 + TypeScript + Vite (frontend). No new dependencies on either side.

**Spec:** `docs/superpowers/specs/2026-10-05-game-notes-and-library-design.md`

## Global Constraints

- **All player-facing strings are Chinese; code, comments, identifiers and commit messages are English.**
- **No LLM anywhere.** This feature adds user-authored text only.
- **No new dependencies.** Import is a JSON body, not multipart (no `python-multipart`). The frontend reads the file with `FileReader`.
- **The engine stays optional.** Library endpoints and note editing must work with the engine down: they must not call `_ensure_engine()`. Only the pre-existing move/undo/redo/new/position endpoints keep that call.
- **Record keys are English and exactly:** `format`, `version`, `id`, `name`, `created_at`, `updated_at`, `start_fen`, `moves`, `notes`, `game_note`, `result`, `winner`. `format == "xiangqi-shifu-game"`, `version == 1`.
- **The record stores no engine output** (no `candidates`/`lines`/`explanation`/`intents`/`tactics`), and no engine settings.
- **Files live in `<repo>/data/games/<id>.json`**, `<id>` matching `[0-9A-Za-z-]+`; `GAMES_DIR` overrides the directory.
- **Backend commands run from `backend/`** (tests import `app.*`); frontend commands run from `frontend/`.
- **`GameSession(engine, store=None)`**: `store=None` must stay a working, purely in-memory session — the 141 existing tests depend on it.

## Review Focus

Inputs and failures the spec implies but only some tasks pin — most likely to bite a user first:

1. **A game id arriving from the URL that contains `..` or a path separator** (`GET /games/..%2F..%2Fsecrets`) — must 404 without ever touching a path outside `data/games/`. Test in Task 2.
2. **A hand-edited or third-party file whose `notes` length ≠ `moves` length** — must be refused with a Chinese message rather than silently shifting notes onto the wrong plies. Tests in Tasks 1 and 4.
3. **A record whose `moves` are illegal from its `start_fen`** (hand-edited, or a whole branch replayed on the wrong side) — must fail the load and leave the live session byte-for-byte as it was. Test in Task 4.
4. **Disk failure during auto-save** (read-only directory, permissions, full disk) — the move must still stand in memory, the failure must surface as `save_error` rather than a 500 or a silent "已保存", and undo/redo must keep working. Tests in Task 4; banner wiring in Task 7.
5. **A note written on a ply that is currently undone, then redone** — the note must return with its ply, and the saved file (the applied line) must not contain the undone ply. Tests in Tasks 3 and 4.

---

### Task 1: The record model

**Files:**
- Create: `backend/app/library/__init__.py` (empty)
- Create: `backend/app/library/records.py`
- Test: `backend/tests/test_library.py`

**Interfaces:**
- Consumes: `app.xiangqi.board.Board`, `Move` (for FEN and UCI validation only).
- Produces: `FORMAT_NAME`, `FORMAT_VERSION`, `RecordError`, `now_iso() -> str`, `mint_id() -> str`, `GameRecord`, `GameSummary`, `GameRecord.parse(data: dict) -> GameRecord`, `summarize(record: GameRecord) -> GameSummary`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_library.py`. Use JSON round-trips through `json.dumps`/`json.loads` in at least one test so the file format itself is exercised, not just the model.

```python
import json

import pytest

from app.library.records import (
    FORMAT_NAME, FORMAT_VERSION, GameRecord, RecordError, summarize,
)

VALID = {
    "format": FORMAT_NAME, "version": FORMAT_VERSION,
    "id": "20261005-1230-a1b2", "name": "中炮对屏风马",
    "created_at": "2026-10-05T12:30:00+08:00", "updated_at": "2026-10-05T13:02:11+08:00",
    "start_fen": None, "moves": ["h2e2", "h9g7"], "notes": ["", "这步太急"],
    "game_note": "这套开局我总是吃亏。", "result": "ongoing", "winner": None,
}


def test_parse_round_trips_through_json():
    record = GameRecord.parse(json.loads(json.dumps(VALID)))
    assert record.notes == ["", "这步太急"]
    assert record.game_note == "这套开局我总是吃亏。"
    assert json.loads(record.model_dump_json())["version"] == FORMAT_VERSION


def test_parse_rejects_a_foreign_file():
    with pytest.raises(RecordError):
        GameRecord.parse({**VALID, "format": "some-other-app"})


def test_parse_rejects_a_newer_version():
    with pytest.raises(RecordError):
        GameRecord.parse({**VALID, "version": FORMAT_VERSION + 1})


def test_parse_rejects_mismatched_note_count():
    # Review Focus 2: a note may never silently land on the wrong ply.
    with pytest.raises(RecordError):
        GameRecord.parse({**VALID, "notes": ["只有一条"]})


def test_parse_rejects_a_broken_start_fen():
    with pytest.raises(RecordError):
        GameRecord.parse({**VALID, "start_fen": "not/a/fen"})


def test_parse_rejects_a_broken_move():
    with pytest.raises(RecordError):
        GameRecord.parse({**VALID, "moves": ["h2e2", "zz"]})


def test_summarize_counts_only_non_empty_notes():
    summary = summarize(GameRecord.parse(VALID))
    assert summary.move_count == 2
    assert summary.note_count == 2  # one ply note + the game note
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_library.py -q`
Expected: `ModuleNotFoundError: No module named 'app.library'`

- [ ] **Step 3: Implement `backend/app/library/records.py`**

`GameRecord` and `GameSummary` are pydantic `BaseModel`s with the exact keys above (`start_fen: str | None`, `notes: list[str]`, `game_note: str = ""`, `result: str = "ongoing"`, `winner: str | None`). `GameRecord.parse(data: dict) -> GameRecord` is a classmethod that validates and **raises `RecordError` with a Chinese message** for each rule:

- `format != FORMAT_NAME` → 「不是象棋师父的复盘文件」
- `version` not an `int`, or `version > FORMAT_VERSION` → 「文件版本过新（v{version}）」; `< 1` → 「文件版本不合法」
- `len(notes) != len(moves)` → 「笔记数量与着法不一致（{len(notes)} ≠ {len(moves)}）」
- `name` emptied by `.strip()` → 「无名对局」 (normalise, do not reject)
- `start_fen` not `None` and `Board.from_fen(start_fen)` raises `(ValueError, IndexError)` → 「起始局面不合法」
- any move failing `Move.from_uci` (raises `ValueError` **or** `IndexError`) → 「着法不合法：{uci}」
- `result` not in `{"ongoing", "checkmate", "stalemate", "draw_repetition", "perpetual_loss"}` → 「未知的终局状态」

`summarize` sets `note_count = sum(1 for n in record.notes if n.strip()) + (1 if record.game_note.strip() else 0)`. `now_iso()` returns `datetime.now().astimezone().isoformat(timespec="seconds")`. `mint_id()` returns `f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"`.

Board legality is **not** checked here — only structure and parseability. Legality needs a board replay and belongs to Task 4.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_library.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/library/__init__.py backend/app/library/records.py backend/tests/test_library.py
git commit -m "Add the replay-file record model and its structural validation"
```

---

### Task 2: The file store

**Files:**
- Create: `backend/app/library/store.py`
- Modify: `.gitignore` (add `data/`)
- Modify: `CLAUDE.md` (add the `library/` line to the layering block)
- Test: `backend/tests/test_library.py` (extend)

**Interfaces:**
- Consumes: `GameRecord`, `GameSummary`, `RecordError`, `now_iso`, `mint_id` (Task 1).
- Produces: `StoreError`, `RecordNotFound(StoreError)`, `GameStore(directory: str | Path)` with `list() -> list[GameSummary]`, `load(game_id) -> GameRecord`, `exists(game_id) -> bool`, `new_id() -> str`, `save(record) -> GameRecord`, `delete(game_id) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_library.py`, adding `from app.library.store import GameStore, RecordNotFound, StoreError` to the imports and using the `tmp_path` fixture:

```python
def test_save_then_load_round_trips(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse(VALID))
    assert store.load(saved.id).name == "中炮对屏风马"
    assert store.load(saved.id).notes == ["", "这步太急"]


def test_save_leaves_no_temp_file_and_stamps_updated_at(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse(VALID))
    assert saved.updated_at != VALID["updated_at"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_list_sorts_newest_first_and_counts_notes(tmp_path):
    store = GameStore(tmp_path)
    store.save(GameRecord.parse({**VALID, "id": "a", "updated_at": "2026-01-01T00:00:00+08:00"}))
    store.save(GameRecord.parse({**VALID, "id": "b", "updated_at": "2026-02-01T00:00:00+08:00"}))
    assert [s.id for s in store.list()] == ["b", "a"]
    assert store.list()[0].note_count == 2


def test_list_skips_a_corrupt_file_instead_of_failing(tmp_path):
    store = GameStore(tmp_path)
    store.save(GameRecord.parse(VALID))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert len(store.list()) == 1


def test_load_of_a_missing_id_raises_not_found(tmp_path):
    with pytest.raises(RecordNotFound):
        GameStore(tmp_path).load("20260101-0000-0000")


def test_load_rejects_a_path_traversal_id(tmp_path):
    # Review Focus 1: ids come straight off a URL path.
    store = GameStore(tmp_path)
    for bad in ["..", "../../etc/passwd", "a/b", "a\\b", ""]:
        with pytest.raises(StoreError):
            store.load(bad)


def test_delete_removes_the_file(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse(VALID))
    store.delete(saved.id)
    assert not store.exists(saved.id)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_library.py -q`
Expected: `ImportError: cannot import name 'GameStore'`

- [ ] **Step 3: Implement `backend/app/library/store.py`**

`GameStore.__init__` stores `Path(directory)` and does **not** create it (created on first save). `_path(game_id)` rejects any id not matching `^[0-9A-Za-z-]+$` with `RecordNotFound` — this is the traversal guard, and it must run **before** any filesystem call, including in `exists` and `delete`.

- `save(record)`: `mkdir(parents=True, exist_ok=True)`; set `record.updated_at = now_iso()`; write `json.dumps(record.model_dump(), ensure_ascii=False, indent=2)` to `<id>.json.tmp` **in the same directory**, then `os.replace()` onto `<id>.json`; wrap `OSError` into `StoreError` with a Chinese message (「保存对局失败：{e}」); return the record.
- `load(game_id)`: read; `json.JSONDecodeError` → `RecordError`「文件不是合法的 JSON」; missing file → `RecordNotFound`「库里没有这局」; delegate structure checks to `GameRecord.parse`.
- `list()`: for each `*.json`, skip (and `print` a warning) anything raising `(RecordError, StoreError, OSError)`; sort by `updated_at` descending.
- `new_id()`: `mint_id()` until `not exists(...)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_library.py -q && python -m pytest -q`
Expected: all pass, existing suite unchanged.

- [ ] **Step 5: Update `.gitignore` and `CLAUDE.md`**

Add `data/` under a new `# Saved games (data/games/*.json)` heading to `.gitignore`. In `CLAUDE.md`'s layering block add, between `game.py` and `api/routes.py`:

```
library/      record model + on-disk game store (data/games/*.json)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/library/store.py backend/tests/test_library.py .gitignore CLAUDE.md
git commit -m "Add the on-disk game store with atomic writes"
```

---

### Task 3: Notes in the session

**Files:**
- Modify: `backend/app/game.py`
- Test: `backend/tests/test_game.py` (extend)

**Interfaces:**
- Produces: `GameSession.move_notes: list[str]`, `GameSession.redo_notes: list[str]`, `GameSession.game_note: str`, `GameSession.set_note(ply: int | None, text: str) -> dict`, `GameSession.line_notes() -> list[str]`, `GameSession._notes_payload() -> dict`.

Notes live and die with their move: `_undo_one` pops the note onto `redo_notes`, `_redo_one` pushes it back, `_play_move` clears `redo_notes` alongside `redo_stack`, `new_game` clears all three. `set_note(ply)` takes a **1-based ply into the whole line** (`move_history` then the redo branch), so a note can be written for a ply that is currently undone; `ply=None` sets `game_note`. `line_notes()` returns `move_notes + list(reversed(redo_notes))` — the whole line in play order, matching `future_moves = list(reversed(redo_stack))`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_game.py` (the existing `session` fixture uses `FakeEngine`):

```python
def test_note_rides_along_with_undo_and_redo(session):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.set_note(2, "黑方这步不好")
    session.undo()
    assert session.line_notes() == ["", "黑方这步不好"]
    session.redo()
    assert session.line_notes() == ["", "黑方这步不好"]
    assert session.move_notes == ["", "黑方这步不好"]


def test_a_new_move_drops_the_abandoned_branch_note(session):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.set_note(2, "不要这步")
    session.undo()
    session.make_move("h9", "g7")
    assert session.line_notes() == ["", ""]
    assert session.move_notes == ["", ""]


def test_set_note_addresses_a_ply_in_the_redo_branch(session):
    # Review Focus 5: a note may be written for a ply that is currently undone.
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.undo()
    session.set_note(2, "先记下，之后再说")
    assert session.move_notes == [""]                    # nothing leaks into the applied line
    assert session.redo_notes == ["先记下，之后再说"]
    assert session.line_notes() == ["", "先记下，之后再说"]
    assert session.redo()["notes"] == ["", "先记下，之后再说"]


def test_set_note_rejects_an_out_of_range_ply(session):
    session.make_move("c3", "c4")
    for bad in (0, 2):
        with pytest.raises(IllegalMoveError):
            session.set_note(bad, "x")


def test_notes_payload_covers_the_whole_line(session):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.undo()
    payload = session.position_payload()
    assert payload["notes"] == ["", ""]
    assert len(payload["notes"]) == len(payload["move_history"]) + len(payload["future_moves"])


def test_whole_game_note_is_separate_from_ply_notes(session):
    session.make_move("c3", "c4")
    session.set_note(None, "整局：开局太软")
    assert session.game_note == "整局：开局太软"
    assert session.move_notes == [""]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_game.py -q -k "note"`
Expected: `AttributeError: 'GameSession' object has no attribute 'set_note'`

- [ ] **Step 3: Implement the note stacks in `backend/app/game.py`**

Add the three state fields to `__init__` and `new_game`; mirror the existing history lines in `_undo_one`, `_redo_one` and `_play_move` (append `""` for a newly played move); add `set_note`, `line_notes`, `_notes_payload`; include `**_notes_payload()` in `position_payload()`.

For the redo branch, the 1-based future index `k = ply - len(move_history)` maps to `redo_notes[len(redo_stack) - k]` (the branch's play order is `reversed(redo_stack)`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_game.py -q`
Expected: old and new tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/game.py backend/tests/test_game.py
git commit -m "Track per-ply and whole-game notes alongside the move history"
```

---

### Task 4: Record lifecycle and auto-save

**Files:**
- Modify: `backend/app/game.py`
- Modify: `CLAUDE.md` (the `GameSession` description in "Architecture")
- Test: `backend/tests/test_game.py` (extend)

**Interfaces:**
- Consumes: `GameRecord`, `GameSummary`, `RecordError`, `now_iso` (Task 1); `GameStore`, `StoreError`, `RecordNotFound` (Task 2); the note stacks (Task 3).
- Produces: `GameSession(engine, store=None)`, `session.store`, `session.record_id`, `session.record_name`, `session.created_at`, `session.saved_at`, `session.save_error`, `session._persist(default_name=None) -> None`, `session._record_fields() -> dict`, `session.save_as(name) -> dict`, `session.open_record(game_id) -> dict`, `session.import_record(record: GameRecord) -> dict`, `session.sync_renamed_record(game_id, name) -> None`, `session._line_plies() -> list[dict]`.

`_record_fields()` returns `{"game_id", "game_name", "saved_at", "save_error"}` and is merged into **both** `position_payload()` and `_play_move`'s return dict.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_game.py`, adding `from app.library.records import GameRecord, RecordError` and `from app.library.store import GameStore, StoreError` to the imports:

```python
@pytest.fixture
def stored(tmp_path):
    """A session with a real store on disk, plus the store itself."""
    store = GameStore(tmp_path)
    session = GameSession(FakeEngine(), store)
    session.new_game()
    return session, store


def test_first_move_creates_the_record_lazily(stored):
    session, store = stored
    assert session.record_id is None
    result = session.make_move("c3", "c4")
    assert result["game_id"] == session.record_id is not None
    assert result["save_error"] is None
    assert len(store.list()) == 1
    assert store.load(session.record_id).moves == ["c3c4"]


def test_undo_rewrites_the_saved_line(stored):
    session, store = stored
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.set_note(2, "黑方这步不好")
    session.undo()
    record = store.load(session.record_id)
    assert record.moves == ["c3c4"]
    assert record.notes == [""]   # Review Focus 5: the undone ply is not in the file


def test_a_failed_save_is_reported_without_losing_the_move(tmp_path):
    # Review Focus 4
    class BrokenStore(GameStore):
        def save(self, record):
            raise StoreError("保存对局失败：磁盘只读")

    session = GameSession(FakeEngine(), BrokenStore(tmp_path))
    session.new_game()
    result = session.make_move("c3", "c4")
    assert result["save_error"] == "保存对局失败：磁盘只读"
    assert session.move_history == ["c3c4"]      # the move still stands
    assert session.undo()["move_history"] == []  # and history still works


def test_import_rejects_a_record_whose_notes_do_not_match_its_moves(tmp_path):
    # Review Focus 2: the API hands the session a pydantic model that was never
    # run through GameRecord.parse, so import_record re-validates.
    session = GameSession(FakeEngine(), GameStore(tmp_path))
    session.new_game()
    with pytest.raises(RecordError):
        session.import_record(GameRecord(**{**VALID, "notes": ["只有一条"]}))


def test_open_record_does_not_bump_updated_at(stored):
    session, store = stored
    session.make_move("c3", "c4")
    before = store.load(session.record_id).updated_at
    session.open_record(session.record_id)
    assert store.load(session.record_id).updated_at == before


def test_open_record_replays_the_same_notation(stored):
    # The guard for coordinate/start-fen mistakes: move_to_chinese needs the
    # board BEFORE the move, so a wrong replay shows up as different text.
    session, store = stored
    for frm, to in [("c3", "c4"), ("c6", "c5"), ("b2", "e2")]:
        session.make_move(frm, to)
    expected = list(session.position_payload()["move_history_chinese"])

    reopened = GameSession(FakeEngine(), store)
    reopened.open_record(session.record_id)
    assert reopened.position_payload()["move_history_chinese"] == expected
    assert reopened.record_id == session.record_id
    assert reopened.saved_at == session.saved_at


def test_line_plies_matches_the_live_move_results(stored):
    # Ties the loaded-game board rendering to reality: the per-ply FENs a
    # library game renders from must equal the ones the live game produced.
    session, _ = stored
    results = [session.make_move("c3", "c4"), session.make_move("c6", "c5")]
    plies = session._line_plies()
    assert [p["fen"] for p in plies] == [r["fen"] for r in results]
    assert [p["move_uci"] for p in plies] == [r["move_uci"] for r in results]
    assert [p["move_chinese"] for p in plies] == [r["move_chinese"] for r in results]
    assert [p["side_to_move"] for p in plies] == [r["side_to_move"] for r in results]


def test_open_record_with_an_illegal_move_leaves_the_session_untouched(stored):
    # Review Focus 3; a0b1 is a diagonal 車 move, so it can never be legal.
    session, store = stored
    session.make_move("c3", "c4")
    broken = GameRecord(**{
        **VALID, "id": "20260101-0000-dead",
        "moves": ["c3c4", "c6c5", "a0b1"], "notes": ["", "", ""],
    })
    store.save(broken)  # save() is a dumb writer — it does not run parse
    with pytest.raises(RecordError):
        session.open_record(broken.id)
    assert session.move_history == ["c3c4"]
    assert session.record_id != broken.id


def test_save_as_copies_the_line_and_switches_identity(stored):
    session, store = stored
    session.make_move("c3", "c4")
    original = session.record_id
    session.save_as("我的研究")
    assert session.record_name == "我的研究"
    assert session.record_id != original
    assert store.load(original).name != "我的研究"
    assert store.load(session.record_id).moves == ["c3c4"]


def test_import_keeps_the_files_id_when_free_and_mints_one_when_taken(stored):
    session, store = stored
    record = GameRecord.parse(VALID)   # h2e2 / h9g7 — legal from the start position
    session.import_record(record)
    assert session.record_id == record.id
    session.import_record(record)      # the same id again
    assert session.record_id != record.id
    assert len(store.list()) == 2


def test_a_session_without_a_store_stays_pure(session):
    result = session.make_move("c3", "c4")
    assert result["game_id"] is None
    assert result["save_error"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_game.py -q -k "record or save or import"`
Expected: `TypeError: GameSession.__init__() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Implement the record lifecycle in `backend/app/game.py`**

- `__init__(self, engine, store=None)`; new fields `record_id/record_name/created_at/saved_at/save_error` (all `None`).
- `_persist(default_name=None)`: no-op when `store is None`; create lazily only when `move_history` is non-empty (name = `default_name` or `f"{datetime.now():%Y-%m-%d %H:%M} 对局"`, `created_at = now_iso()`); build the `GameRecord` from the applied line (`moves=list(self.move_history)`, `notes=list(self.move_notes)`, `game_note`, `start_fen=self.start_fen`, `result`/`winner` from `self.status_payload()` — no engine call); `self.store.save(record)`; on success set `saved_at` from the returned record and clear `save_error`; on `(RecordError, StoreError, OSError)` set `save_error = str(e)` and leave everything else alone.
- `_load_record(record)`: replay onto a **scratch** board (`Board.from_fen(record.start_fen or START_FEN)`), collecting `history/notes/sides/checks/keys` locally, and assign into `self` only after the last move succeeds, so a failure leaves the session untouched. `find_legal_move` returning `None` → `RecordError(f"第 {n} 步着法不合法：{uci}")`. On commit: clear the redo stacks, copy the record identity, set `saved_at = record.updated_at`, clear `_cached_lines`, and `engine.new_game()` when the engine is running.
- `open_record(game_id)`: `store.load` then `_load_record`; raise `StoreError("对局库未启用")` when `store is None`. **Does not persist.**
- `import_record(record)`: **re-validate first** — `record = GameRecord.parse(record.model_dump())` — because the HTTP layer may hand over a pydantic model that never ran through `parse`, then `_load_record` (which validates move legality before writing), then mint a new id if the file's id is taken, then `store.save(record.model_copy(update={"id": self.record_id}))` and set `saved_at`.
- `_line_plies()`: replay `start_fen` + `move_history` on a scratch board and return one dict per ply — `{"move_uci", "move_chinese", "fen", "side_to_move"}` — where `fen`/`side_to_move` are the position **after** that ply (the same convention as `MoveResultResponse`), and `move_chinese` comes from `moves_to_chinese(Board.from_fen(self.start_fen), self.move_history)`. Pure board work, no engine. This is what lets a game opened off disk render ply by ply.
- `save_as(name)`: raise `IllegalMoveError("还没有走子，无法另存为")` when `move_history` is empty; otherwise clear the identity (`record_id = None`, `created_at = None`), set `record_name`, `_persist()`.
- `sync_renamed_record(game_id, name)`: under the lock, update `record_name` when `record_id == game_id`.
- Call `_persist(...)` at the end of `_play_move` (with the move's `opening_name` as `default_name`), `undo`, `redo`, `goto` and `set_note`, and merge `_record_fields()` into both payload dicts. **There is no `GameSession.rename`** — renaming goes through the store (Task 5) so it can target a library entry that is not the open game; the open game is kept in sync by `sync_renamed_record`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest -q`
Expected: the whole suite passes.

- [ ] **Step 5: Update `CLAUDE.md`**

In "Architecture", replace the `GameSession` paragraph's "no DB, no persistence" claim with the new reality: one in-memory game plus an auto-saving record (`data/games/<id>.json`); notes are parallel stacks (`move_notes`/`redo_notes`) that mirror `move_history`/`redo_stack`; `store=None` keeps a session purely in memory for tests; `open_record`/`import_record` do not persist (opening a game must not bump `updated_at`). State that the record deliberately stores no engine output.

- [ ] **Step 6: Commit**

```bash
git add backend/app/game.py backend/tests/test_game.py CLAUDE.md
git commit -m "Auto-save the current game to the library on every mutation"
```

---

### Task 5: The HTTP layer

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `docs/api-contract.md`
- Test: manual smoke test (below) + `python -m pytest -q`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces (wire): `PositionResponse` / `MoveResultResponse` gain `game_id: str | None`, `game_name: str | None`, `saved_at: str | None`, `save_error: str | None`; `PositionResponse` also gains `game_note: str` and `notes: list[str]`; new `NoteRequest`, `NoteResponse`, `RenameRequest`, `SaveAsRequest`, `OpenRequest`, `PlyViewOut`, `LoadedGameResponse`; `GameRecord`/`GameSummary` re-exported from `schemas.py`.

- [ ] **Step 1: Add the schemas**

`NoteRequest(ply: int | None, text: str)`, `NoteResponse(notes: list[str], game_note: str, saved_at: str | None, save_error: str | None)`, `RenameRequest(name: str)`, `SaveAsRequest(name: str)`, `OpenRequest(id: str)`. Re-export the record models so `schemas.py` stays the one place the wire contract is read from:

```python
from ..library.records import GameRecord, GameSummary  # the 复盘文件 shape
```

A game opened from disk has no cached `MoveResultResponse` per ply, and the frontend cannot compute a board position per ply itself (`board/fen.ts` only parses for rendering). So `open` and `import` answer with a subclass that carries the whole line:

```python
class PlyViewOut(BaseModel):
    move_uci: str
    move_chinese: str | None
    fen: str            # the position AFTER this ply
    side_to_move: str   # the side to move AFTER this ply, as in MoveResultResponse


class LoadedGameResponse(PositionResponse):
    plies: list[PlyViewOut]
```

Only `POST /game/open` and `POST /games/import` use `LoadedGameResponse`; every other endpoint keeps `PositionResponse`, so undo/redo/new after opening stay lean.

- [ ] **Step 2: Add the routes**

In `routes.py`, resolve `GAMES_DIR` exactly like `ENGINE_PATH` (repo root + `data/games`, env override) and construct `_session = GameSession(_engine, GameStore(GAMES_DIR))`.

| Route | Behavior |
|---|---|
| `GET /games` | `_session.store.list()` |
| `GET /games/{game_id}` | `store.load`; `RecordNotFound` → 404, `RecordError`/`StoreError` → 400 |
| `POST /games/import` | body is a **raw JSON object** (`body: dict`), and the route runs `GameRecord.parse(body)` itself (`RecordError` → 400). A `GameRecord` request model would skip every rule in `parse`. Returns `LoadedGameResponse` |
| `PATCH /games/{game_id}` | load → set `name` (strip; empty → 400 「名字不能为空」; > 80 chars → 400 「名字太长了」) → `store.save` → `_session.sync_renamed_record(game_id, name)` → return the summary |
| `DELETE /games/{game_id}` | 409 「这是当前对局，请先开新对局」 when `game_id == _session.record_id`; else `store.delete`; return `{"deleted": game_id}` |
| `POST /game/save_as` | `_session.save_as(req.name)`; `IllegalMoveError` → 400 |
| `POST /game/open` | `{**_session.open_record(req.id), "plies": _session._line_plies()}`; 404 / 400 |
| `PUT /game/note` | `_session.set_note(req.ply, req.text)`; `IllegalMoveError` → 400 |

Declare `POST /games/import` **before** the `/{game_id}` routes. **None of these eight calls `_ensure_engine()`** — they must work with the engine down (library browsing especially).

- [ ] **Step 3: Run the suite**

Run: `python -m pytest -q`
Expected: all pass (the API layer has no automated tests in this repo; the layers beneath it do).

- [ ] **Step 4: Smoke-test the wiring with the real HTTP layer**

Run from `backend/`: `uvicorn app.main:app --host 127.0.0.1 --port 8000` (background), then

```bash
curl -s http://127.0.0.1:8000/api/games                          # → []
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/games/nope   # → 404
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/games/..%2F..%2Fsecrets  # → 404
```

Expected: `[]`, `404`, `404`. The engine-move endpoints are exercised in Task 10.

- [ ] **Step 5: Update `docs/api-contract.md`**

Add the eight endpoints, the new fields on both response models (and *why* `notes` in a response covers the redo branch while `notes` in a file does not), and a 「对局文件格式」 section with the example object, the field rules, and the "no engine output is stored" rationale.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/routes.py docs/api-contract.md
git commit -m "Expose the game library and note editing over HTTP"
```

---

### Task 6: Frontend types and API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

**Interfaces:**
- Produces: `GameSummary`, `GameRecord`, `NoteResponse`, `PlyView`, `LoadedGameResponse`, `PlyEntry`; the four record fields on both response interfaces; `api.listGames()`, `api.getGame(id)`, `api.importGame(record)`, `api.renameGame(id, name)`, `api.deleteGame(id)`, `api.saveAs(name)`, `api.openGame(id)`, `api.setNote(ply, text)`.

- [ ] **Step 1: Add the types**

`GameSummary { id, name, created_at, updated_at, move_count: number, note_count: number, result: GameStatus, winner: Side | null }`; `GameRecord { format: string, version: number, id, name, created_at, updated_at, start_fen: string | null, moves: string[], notes: string[], game_note: string, result: GameStatus, winner: Side | null }`; `NoteResponse { notes: string[], game_note: string, saved_at: string | null, save_error: string | null }`. Add `game_id`, `game_name`, `saved_at`, `save_error` to `PositionResponse` and `MoveResultResponse`, and `notes: string[]` + `game_note: string` to `PositionResponse`.

For games opened off disk, which answer with the whole line (Task 5):

```ts
export interface PlyView {
  move_uci: string;
  move_chinese: string | null;
  fen: string;         // the position AFTER this ply
  side_to_move: Side;  // the side to move AFTER this ply
}
export type LoadedGameResponse = PositionResponse & { plies: PlyView[] };

/** A ply from a game opened off disk: position, notation and notes only.
 * Engine analysis is regenerated only for moves played in this session. */
export type PlyEntry = MoveResultResponse & { loaded_only?: boolean };
```

- [ ] **Step 2: Add the client methods**

Every one goes through the existing `request<T>()` helper (which needs a JSON body on every response, including the DELETE — hence the `{"deleted": id}` shape). `setNote` sends `{ ply, text }` with `ply: number | null`; `openGame` and `importGame` are typed `Promise<LoadedGameResponse>`; `saveAs` returns a plain `PositionResponse` (the line does not move).

- [ ] **Step 3: Verify**

Run from `frontend/`: `npx tsc -b && npx oxlint .`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "Add the game-library and note types and client calls"
```

---

### Task 7: Notes and record state in `useGame`

**Files:**
- Modify: `frontend/src/state/useGame.ts`

**Interfaces:**
- Consumes: Task 6.
- Produces (hook surface): `notes: string[]`, `gameNote: string`, `gameId: string | null`, `gameName: string | null`, `savedAt: string | null`, `noteSaving: boolean`, and actions `setNote(ply: number | null, text: string)`, `openGame(id: string)`, `importRecord(record: GameRecord)`, `saveAs(name: string)`.

- [ ] **Step 1: Extend the timeline and status plumbing**

`Timeline` gains `notes: string[]`; `EMPTY` gains `notes: []`; `recordResult` appends `""` and truncates with the same `slice(0, pointer)` rule as `moves`. Extend `applyStatus`'s parameter type with the four record fields and set them there, so every existing call site (`startNewGame`, `undo`, `redo`, `recordResult`) starts carrying them for free. Add `gameNote` state, replaced from `PositionResponse.game_note` on new/undo/redo/open/import and cleared on new game.

- [ ] **Step 2: Add the actions**

- `setNote(ply, text)`: set `noteSaving`, call `api.setNote`, then replace `notes`/`gameNote`/`savedAt` from the response. Guard with a `useRef` sequence counter and apply only the newest response (a debounced note save can otherwise land after a newer one). Route a non-null `save_error` into the existing `error` state (**Review Focus 4**).
- `openGame(id)` / `importRecord(record)`: call the API, then `applyStatus(res)`, set `notes`/`gameNote`, **disarm `autoPlayArmed`**, synthesise one placeholder per ply from `res.plies` (below), and set `pointer = viewPly = plies.length`. Disarming matters: with a side set to 引擎, an armed auto-play would make the engine move in the freshly opened game and auto-save that move into the record the player just opened to look at. 已暂停 already has a UI (`enginePaused`), and playing a move re-arms it.
- `saveAs(name)`: call the API, then `applyStatus(res)` — the line and notes are unchanged, only the identity moves.

A game opened off disk uses the **same** `Timeline.moves` model as a live game, because `LoadedGameResponse.plies` already carries a board per ply — no second code path for the board, the move list or history browsing. `Timeline.moves` becomes `PlyEntry[]` (Task 6). Synthesise each placeholder from `plies[i]` (`fen`, `move_uci`, `move_chinese`, `side_to_move`) plus inert values: `played_matches_best: false`, `best_move_uci: null`, `best_move_chinese: null`, `label: "—"`, `label_en: "none"`, `color: "#cfcabb"`, `cp_loss: 0`, `eval_cp: null`, `candidates: []`, `why_better: null`, `intent_text: null`, `intents: []`, `follow_up: null`, `passing_plan: null`, `best_passing_plan: null`, `explanation: ""`, `tactics: []`, `opening_name: null`, `opening_note: null`, `in_book: false`, `left_book_now: false`, `game_status: "ongoing"`, `result_note: null`, `in_check: false`, `winner: null`, `loaded_only: true`. **Manufacturing a label or an eval here would be a lie the UI then displays** — an unanalysed ply is labelled as unanalysed.

`recordResult` keeps its `slice(0, pointer)` truncation, so playing a move after opening appends a real result after the loaded prefix.

- [ ] **Step 3: Verify**

Run: `npm run build` from `frontend/`.
Expected: typecheck and build pass. Nothing renders the placeholders yet — that is Task 9.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/state/useGame.ts
git commit -m "Carry notes and record identity in the game state"
```

---

### Task 8: The notes card

**Files:**
- Create: `frontend/src/components/NotePanel.tsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/App.tsx` (render it in `layout__scroll` under `ConceptPanel`)

**Interfaces:**
- Consumes: Task 7's hook surface.
- Produces: `<NotePanel ply={number} moveLabel={string | null} notes={string[]} gameNote={string} savedAt={string | null} saving={boolean} onSave={(ply: number | null, text: string) => void} onJump={(ply: number) => void} />`.

- [ ] **Step 1: Build the component**

Two tabs, 「这一步」/「整局」. Header shows 「共 N 条」 counting non-empty ply notes, and a dot on the 整局 tab when `gameNote` is non-empty. The 这一步 tab titles the target (第 N 步 · 红 马八进七) and carries 「◀ / ▶」 buttons jumping to the previous/next ply that has a note (disabled when none; they call `onJump(ply)`, which is `viewPlyAt`). At `ply === 0` the 这一步 tab shows a hint (「走到某一步或在上面的棋谱里点一步，就能给它写笔记」) instead of a textarea.

Save behavior, all four points required:

1. Switching tab or ply loads that target's stored text into the textarea.
2. Typing saves 500 ms after the last keystroke.
3. Switching tab/ply or unmounting **saves any pending edit to the target it was written for**, not to the new one (keep the pending `{target, text}` in a ref).
4. The corner shows 保存中 while `saving`, else 已保存 HH:MM from `savedAt` (format the ISO string's time part), else nothing.

- [ ] **Step 2: Style it**

Add `.note__tabs`, `.note__tab`, `.note__tab--active`, `.note__editor` (a `textarea` with `resize: vertical`, min-height ~72px), `.note__status`, `.note__jump` to `index.css`, following the existing `--card`/`--line`/`--muted` variables and `.card` conventions. It must live inside `layout__scroll` so the coaching column keeps absorbing its own overflow — **do not add a column** (`useBoardFit`'s `RESERVED_W` is a hard-coded budget).

- [ ] **Step 3: Verify**

Run: `npx tsc -b && npx oxlint .`, then start the app and check by hand: type in the 这一步 tab, watch 保存中 → 已保存, switch plies and confirm each ply's own text returns, switch to 整局 and back, then reload the page and confirm the text is still there (it round-tripped through the backend).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/NotePanel.tsx frontend/src/index.css frontend/src/App.tsx
git commit -m "Add the per-move and whole-game notes card"
```

---

### Task 9: The game library modal

**Files:**
- Create: `frontend/src/components/GameLibrary.tsx`
- Modify: `frontend/src/components/ConceptPanel.tsx`
- Modify: `frontend/src/components/Controls.tsx`
- Modify: `frontend/src/components/MoveList.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: Task 6's client, Task 7's hook surface.
- Produces: `<GameLibrary open currentId onClose onOpen(id) onImport(record) onSaveAs(name) onError(msg) />`; `MoveEntry` gains `hasNote: boolean`; `Controls` gains `gameName`, `savedAt`, `saveError`, `onOpenLibrary`.

- [ ] **Step 1: Build the modal**

`GameLibrary` fetches `api.listGames()` when it opens (and after each rename/delete) and renders rows of name / date / 「N 步 · M 条笔记」 / result, with 打开 · 改名 · 导出 · 删除. 改名 edits the row inline (an input + 确定/取消), calling `api.renameGame`. 删除 calls `api.deleteGame` and is disabled with a 当前对局 tooltip when `id === currentId`. 导出 calls `api.getGame(id)`, then downloads a Blob named `<sanitised name>.xqsf.json` (replace anything outside `[\w一-龥 -]` with `_`). 「从文件导入」 uses a hidden `<input type="file" accept=".json,application/json">`, reads it with `FileReader`, and calls `onImport(JSON.parse(text))`; a parse failure or a 400 surfaces through `onError`. 打开 calls `onOpen(id)` and closes.

Header of the modal also carries 「另存为：[input] [保存副本]」 calling `onSaveAs(name)`, then closes. (Deliberate refinement of the spec: 另存为 and 改名 both need a name input, so they share the modal's input pattern; `window.prompt` is not acceptable UI.)

- [ ] **Step 2: Wire the page**

`App.tsx`: hold `libraryOpen` state; render `<GameLibrary …/>`; pass `gameName`/`savedAt`/`saveError`/`onOpenLibrary` to `Controls` (which renders the name, a 已保存/未保存 indicator, and a 「对局库」 button next to 新对局); build `MoveEntry.hasNote` from `notes[i].trim() !== ""` and pass the note text so `MoveList` renders a `✎` marker on those rows and puts the note in the row's `title`. Loaded plies render through the normal path (`MoveList`'s `—` label, the board from `fen`); the one thing that must change is the 讲解 card, which would otherwise show an empty paragraph for a ply that was never analysed. When `current?.loaded_only`, `ConceptPanel` renders a hint instead: 「这是从对局库打开的棋谱：可以逐步回看、写笔记；引擎讲解只为你在这里走的棋生成。」

- [ ] **Step 3: Style it**

`.modal-backdrop` (`position: fixed; inset: 0; background: rgba(0,0,0,.35); display: flex; align-items: center; justify-content: center; z-index: 20`), `.modal` (card-like, `max-width: 560px`, `max-height: 80dvh`, internal `overflow-y: auto` for the list), `.lib__row`, `.lib__actions`. The app never scrolls the page itself; the modal scrolls internally.

- [ ] **Step 4: Verify**

Run: `npx tsc -b && npx oxlint .`, then by hand: open the modal, rename the current game (Controls' name updates), export it, delete it (the button is disabled for the current game), import the exported file back, confirm the notes are on the right plies and the board shows the final position, then play one more move.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GameLibrary.tsx frontend/src/components/Controls.tsx frontend/src/components/MoveList.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "Add the game library modal, exports and imports"
```

---

### Task 10: End-to-end acceptance

**Files:** none (verification only; fix findings where they belong and re-run).

- [ ] **Step 1: Run both suites**

From `backend/`: `python -m pytest -q` → all pass.
From `frontend/`: `npx tsc -b && npx oxlint .` → clean.

- [ ] **Step 2: Walk the whole feature with the real engine**

Start the backend and frontend, then in the browser:

1. 新对局 → play 6 moves → the library modal shows one entry, named after the opening.
2. Write a note on ply 3 and a whole-game note; the `✎` appears on ply 3 only; ◀/▶ jump to it.
3. 悔棋 twice → the note on ply 3 behaves per Review Focus 5 (if ply 3 is now undone, editing it writes to the redo branch; after 重做 it is back).
4. Reload the page, open the game from the library: the same line, the same notes, and the notation reads identically.
5. Export it; delete it; import the file back; play one more move; 另存为 a copy; confirm the original still has its old line.
6. Turn the engine off (stop it / set a bad `ENGINE_PATH`, restart the backend) and confirm 对局库 list/open/rename/export still work.

- [ ] **Step 3: Confirm the file on disk**

Open `data/games/<id>.json` and verify: `notes` is exactly as long as `moves`, `game_note` is present, no engine output is stored, and `updated_at` moved on the last edit but not on the open.

- [ ] **Step 4: Report**

Summarize any deviation found, then commit any fixes with the task they belong to.
