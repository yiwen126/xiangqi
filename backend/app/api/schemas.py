from __future__ import annotations

from pydantic import BaseModel

# Re-exported so this module stays the one place the wire contract is read
# from: the 复盘 file shape is part of what the frontend talks to.
from ..library.records import GameRecord, GameSummary


class NewGameRequest(BaseModel):
    fen: str | None = None


class MoveRequest(BaseModel):
    from_sq: str  # e.g. "h2"
    to_sq: str    # e.g. "e2"


class GotoRequest(BaseModel):
    ply: int  # 0 = starting position


class StepRequest(BaseModel):
    """悔棋/重做 request. Multi-ply matters because in an engine game a single
    undo lands on the engine's turn, which would simply be replayed."""
    plies: int = 1


class NoteRequest(BaseModel):
    ply: int | None  # 1-based over the whole line; null = the whole game
    text: str


class RenameRequest(BaseModel):
    name: str


class SaveAsRequest(BaseModel):
    name: str


class OpenRequest(BaseModel):
    id: str


class PvLineOut(BaseModel):
    multipv: int
    score_cp: int | None
    score_mate: int | None
    pv: list[str]


class CandidateOut(BaseModel):
    """One of the engine's top choices for the position BEFORE the move.
    Scores are from the MOVER's point of view (positive = good for them)."""
    rank: int
    move_uci: str
    move_chinese: str | None
    score_cp: int | None
    score_mate: int | None
    pv_uci: list[str]
    pv_chinese: list[str]
    is_played: bool


class TacticOut(BaseModel):
    kind: str
    side: str
    piece: str
    piece_name: str
    square: str
    square_chinese: str
    targets: list[str]
    targets_chinese: list[str]


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


class PassingPlanOut(BaseModel):
    """Up to ten consecutive moves for the mover in the hypothetical where the
    opponent keeps passing (chained side-flipped "null move" positions);
    display-only."""
    moves_uci: list[str]
    moves_chinese: list[str | None]


class MoveResultResponse(BaseModel):
    fen: str
    side_to_move: str
    move_uci: str
    move_chinese: str
    played_matches_best: bool
    best_move_uci: str | None
    best_move_chinese: str | None
    label: str
    label_en: str
    color: str
    cp_loss: int
    eval_cp: int | None
    candidates: list[CandidateOut]
    why_better: str | None
    intent_text: str | None
    intents: list[IntentOut]
    lines: list[PvLineOut]
    follow_up: FollowUpOut | None
    passing_plan: PassingPlanOut | None
    best_passing_plan: PassingPlanOut | None
    explanation: str
    tactics: list[TacticOut]
    opening_name: str | None
    opening_note: str | None
    in_book: bool
    left_book_now: bool
    game_status: str
    result_note: str | None
    in_check: bool
    winner: str | None
    # The library identity of the game in flight; all null until the first
    # move auto-creates the record (or a game is opened/imported).
    game_id: str | None
    game_name: str | None
    saved_at: str | None
    save_error: str | None


class PositionResponse(BaseModel):
    fen: str
    side_to_move: str
    game_status: str
    in_check: bool
    winner: str | None
    result_note: str | None
    move_history: list[str]
    move_history_chinese: list[str]
    future_moves: list[str]
    # Notes run parallel to move_history + future_moves: the applied line
    # first, then the redo branch in play order. `game_note` covers the game
    # as a whole; empty strings mean "no note on this ply".
    notes: list[str]
    game_note: str
    # The library identity of the game in flight; all null until the first
    # move auto-creates the record (or a game is opened/imported).
    game_id: str | None
    game_name: str | None
    saved_at: str | None
    save_error: str | None
    lines: list[PvLineOut]


class PlyViewOut(BaseModel):
    """One ply of a game loaded from the library, with the position AFTER it —
    the same convention as MoveResultResponse, so a game opened off disk can
    be rendered ply by ply without the frontend replaying the moves."""
    move_uci: str
    move_chinese: str | None
    fen: str
    side_to_move: str


class LoadedGameResponse(PositionResponse):
    """The answer to 打开/导入: the live position plus the whole saved line.
    Only those two endpoints carry `plies` — undo/redo/new after opening stay
    lean."""
    plies: list[PlyViewOut]


class NoteResponse(BaseModel):
    """The note line as it stands after a write. There is no engine output to
    return and no position to report — a note changes neither."""
    notes: list[str]
    game_note: str
    saved_at: str | None
    save_error: str | None
