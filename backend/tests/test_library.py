import json

import pytest

from app.library.records import (
    FORMAT_NAME, FORMAT_VERSION, GameRecord, RecordError, summarize,
)
from app.library.store import GameStore, RecordNotFound, StoreError

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


def test_parse_rejects_a_record_missing_required_fields():
    # A hand-edited file with a field removed must not escape as a raw
    # pydantic ValidationError — the store and the API both catch RecordError.
    with pytest.raises(RecordError):
        GameRecord.parse({"format": FORMAT_NAME, "version": FORMAT_VERSION, "moves": []})


@pytest.mark.parametrize("data", [
    [1, 2, 3],                                   # valid JSON, wrong top-level type
    {**VALID, "name": 42},
    {**VALID, "moves": 5},
    {**VALID, "notes": 5},
    {**VALID, "result": []},
    {**VALID, "start_fen": 42},
    {**VALID, "moves": ["h2e2", 1]},
])
def test_parse_raises_record_error_for_type_malformed_input(data):
    # The store's list() only catches RecordError — anything else here takes
    # the whole library listing down with one bad file.
    with pytest.raises(RecordError):
        GameRecord.parse(data)


def test_summarize_counts_only_non_empty_notes():
    summary = summarize(GameRecord.parse(VALID))
    assert summary.move_count == 2
    assert summary.note_count == 2  # one ply note + the game note


def test_save_then_load_round_trips(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse(VALID))
    assert store.load(saved.id).name == "中炮对屏风马"
    assert store.load(saved.id).notes == ["", "这步太急"]


def test_save_leaves_no_temp_file_and_stamps_updated_at(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse({**VALID, "updated_at": "2000-01-01T00:00:00+08:00"}))
    assert saved.updated_at > "2000-01-01T00:00:00+08:00"  # stamped at write time
    assert list(tmp_path.glob("*.tmp")) == []


def test_list_sorts_newest_first_and_counts_notes(tmp_path):
    # Written by hand, not through save(): save() stamps updated_at. The ids
    # deliberately run OPPOSITE to the timestamps, so an id-only sort fails.
    for game_id, updated in [("a", "2026-02-01T00:00:00+08:00"), ("b", "2026-01-01T00:00:00+08:00")]:
        (tmp_path / f"{game_id}.json").write_text(
            json.dumps({**VALID, "id": game_id, "updated_at": updated}), encoding="utf-8"
        )
    store = GameStore(tmp_path)
    assert [s.id for s in store.list()] == ["a", "b"]
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


def test_an_undecodable_file_is_skipped_not_fatal(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse(VALID))
    (tmp_path / "bad.json").write_bytes(b"\xff\xfe\x00 not utf-8")
    assert [s.id for s in store.list()] == [saved.id]  # one row, and it is the good one
    with pytest.raises(RecordError):
        store.load("bad")


def test_delete_removes_the_file(tmp_path):
    store = GameStore(tmp_path)
    saved = store.save(GameRecord.parse(VALID))
    store.delete(saved.id)
    assert not store.exists(saved.id)
