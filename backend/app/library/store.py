"""On-disk storage for saved games: one JSON file per game, named <id>.json.

A saved game must survive a crash mid-write, so a save writes a temporary file
beside the target and moves it into place — a reader never sees a half-written
file, only the previous complete one or the new one. The store is deliberately
dumb: it owns paths, reads and writes, and nothing else. It never touches a
board, the engine or FastAPI, so the library keeps working with the engine down.

Ids arrive from URL paths and from imported files, so every path this module
builds goes through the same charset check first.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .records import (
    GameRecord, GameSummary, RecordError, mint_id, now_iso, summarize,
)

_ID_RE = re.compile(r"^[0-9A-Za-z-]+$")


class StoreError(RuntimeError):
    """A store operation failed against the filesystem. The message is
    player-facing Chinese."""


class RecordNotFound(StoreError):
    """The requested game is not in the library (or its id is not usable)."""


class GameStore:
    """A directory of <id>.json replay files.

    The directory is created lazily on the first save, so constructing a store
    (which the API does at import time) has no filesystem side effect.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _path(self, game_id: str) -> Path:
        """Turn an id into its file path, refusing anything that is not a
        plain id first. The check runs before any filesystem call so a URL
        path such as `../../etc/passwd` can never be resolved."""
        if not isinstance(game_id, str) or not _ID_RE.fullmatch(game_id):
            raise RecordNotFound("对局编号不合法")
        return self.directory / f"{game_id}.json"

    def exists(self, game_id: str) -> bool:
        """Whether the id has a file. A regex-valid id the filesystem still
        cannot turn into a path (a 300-character id from an imported file)
        fails like any other store operation, not as a raw OSError — the API
        answers a Chinese 400 instead of an unhandled 500."""
        try:
            return self._path(game_id).is_file()
        except OSError as exc:
            raise StoreError(f"读取对局失败：{exc}") from exc

    def new_id(self) -> str:
        """A fresh id that no file in the directory uses yet."""
        game_id = mint_id()
        while self.exists(game_id):
            game_id = mint_id()
        return game_id

    def save(self, record: GameRecord) -> GameRecord:
        """Write the record and return it with a fresh updated_at, which is
        what the caller reports as the game's saved time."""
        target = self._path(record.id)  # guard before touching the filesystem
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            record.updated_at = now_iso()
            temp = target.with_name(target.name + ".tmp")
            temp.write_text(
                json.dumps(record.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp, target)
        except OSError as exc:
            raise StoreError(f"保存对局失败：{exc}") from exc
        return record

    def load(self, game_id: str) -> GameRecord:
        """Every way a file can be unreadable surfaces as RecordNotFound,
        RecordError or StoreError, so list() can skip one bad file instead of
        letting it take the whole library down. Bytes that are not UTF-8 count
        as a bad file, not a crash."""
        path = self._path(game_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:  # an OSError; must be caught first
            raise RecordNotFound("库里没有这局") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordError("文件不是合法的 JSON") from exc
        except OSError as exc:
            raise StoreError(f"读取对局失败：{exc}") from exc
        return GameRecord.parse(data)

    def list(self) -> list[GameSummary]:
        """Summaries of every readable game, newest first. One unreadable file
        is skipped — a single bad file must not take the whole library down."""
        summaries = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                summaries.append(summarize(self.load(path.stem)))
            except (RecordError, StoreError, OSError) as exc:
                print(f"跳过无法读取的对局文件 {path.name}：{exc}")
                continue
        # updated_at has one-second resolution, so two games saved in the same
        # second tie; ids are minted from the timestamp, so the id orders them
        # the same way the clock would have.
        summaries.sort(key=lambda s: (s.updated_at, s.id), reverse=True)
        return summaries

    def delete(self, game_id: str) -> None:
        try:
            self._path(game_id).unlink(missing_ok=True)
        except OSError as exc:
            raise StoreError(f"删除对局失败：{exc}") from exc
