"""The replay-file record model.

A saved game is one plain JSON object carrying only the player's own game:
moves, notes and a result snapshot. Engine output is deliberately absent — it
is large, fully recomputable, and would make an exported file brittle.

This module owns that file's shape and the structural checks an imported file
must pass before a session replays it. It imports nothing from the engine, the
analysis layer or FastAPI, so the library keeps working with the engine down.
Move legality is not checked here: proving the moves are legal needs a board
replay, which belongs to the session, not the file format.
"""
from __future__ import annotations

import secrets
from datetime import datetime

from pydantic import BaseModel, ValidationError

from ..xiangqi.board import Board, Move

FORMAT_NAME = "xiangqi-shifu-game"
FORMAT_VERSION = 1

_RESULTS = {"ongoing", "checkmate", "stalemate", "draw_repetition", "perpetual_loss"}


class RecordError(ValueError):
    """A file that is not a usable replay: foreign format, newer version, or a
    structural mismatch. The message is player-facing Chinese."""


def now_iso() -> str:
    """Local time with its UTC offset, to seconds — the record is written and
    read on this machine, and the offset keeps the shown time honest."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def mint_id() -> str:
    """Sortable timestamp plus four hex characters, so two games created in
    the same second do not collide."""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


class GameRecord(BaseModel):
    format: str
    version: int
    id: str
    name: str
    created_at: str
    updated_at: str
    start_fen: str | None
    moves: list[str]
    notes: list[str]
    game_note: str = ""
    result: str = "ongoing"
    winner: str | None = None

    @classmethod
    def parse(cls, data: dict) -> "GameRecord":
        """Validate a decoded replay file and return a new, normalised record.

        The caller's dict is never mutated. A blank name is normalised rather
        than rejected, because a nameless game is a valid game. Only structure
        is checked — a syntactically valid record may still describe illegal
        moves, which the session catches on replay.

        Every failure surfaces as RecordError: the specific checks below raise
        their own Chinese messages, and the surrounding handler turns a
        missing or wrongly-typed field (anything the checks did not anticipate)
        into the generic one. The library listing catches RecordError alone, so
        no single malformed file may crash it.
        """
        try:
            if data.get("format") != FORMAT_NAME:
                raise RecordError("不是象棋师父的复盘文件")

            version = data.get("version")
            if not isinstance(version, int) or version > FORMAT_VERSION:
                raise RecordError(f"文件版本过新（v{version}）")
            if version < 1:
                raise RecordError("文件版本不合法")

            moves = list(data.get("moves") or [])
            notes = list(data.get("notes") or [])
            if len(notes) != len(moves):
                raise RecordError(f"笔记数量与着法不一致（{len(notes)} ≠ {len(moves)}）")

            start_fen = data.get("start_fen")
            if start_fen is not None:
                try:
                    Board.from_fen(start_fen)
                except (ValueError, IndexError) as exc:
                    raise RecordError("起始局面不合法") from exc

            for uci in moves:
                try:
                    Move.from_uci(uci)
                except (ValueError, IndexError) as exc:
                    raise RecordError(f"着法不合法：{uci}") from exc

            result = data.get("result", "ongoing")
            if result not in _RESULTS:
                raise RecordError("未知的终局状态")

            try:
                return cls(
                    format=FORMAT_NAME,
                    version=version,
                    id=data.get("id"),
                    name=(data.get("name") or "").strip() or "无名对局",
                    created_at=data.get("created_at"),
                    updated_at=data.get("updated_at"),
                    start_fen=start_fen,
                    moves=moves,
                    notes=notes,
                    game_note=data.get("game_note") or "",
                    result=result,
                    winner=data.get("winner"),
                )
            except ValidationError as exc:
                raise RecordError("文件字段不完整或格式不对") from exc
        except RecordError:
            raise  # our own specific messages win
        except (TypeError, AttributeError, KeyError, IndexError, ValueError) as exc:
            # The file decoded as JSON but is structurally unusable — a wrong
            # top-level type, a non-string where text is read, an unhashable
            # result. Only RecordError may escape, for the store's sake.
            raise RecordError("文件字段不完整或格式不对") from exc


class GameSummary(BaseModel):
    """The library-list row: enough to render the list without loading a game."""

    id: str
    name: str
    created_at: str
    updated_at: str
    move_count: int
    note_count: int
    result: str
    winner: str | None


def summarize(record: GameRecord) -> GameSummary:
    return GameSummary(
        id=record.id,
        name=record.name,
        created_at=record.created_at,
        updated_at=record.updated_at,
        move_count=len(record.moves),
        note_count=sum(1 for n in record.notes if n.strip())
        + (1 if record.game_note.strip() else 0),
        result=record.result,
        winner=record.winner,
    )
