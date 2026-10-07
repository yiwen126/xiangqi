"""Game-level rules built on top of movegen: legality checks and game status."""
from __future__ import annotations

from .board import Board, Move, other_side
from .movegen import is_checkmate, is_in_check, is_stalemate, legal_moves


def find_legal_move(board: Board, move: Move) -> Move | None:
    """Return the matching legal Move for the given from/to squares, or None
    if that move is illegal in the current position."""
    for mv in legal_moves(board, board.side_to_move):
        if mv.from_sq == move.from_sq and mv.to_sq == move.to_sq:
            return mv
    return None


def game_status(board: Board) -> dict:
    side = board.side_to_move
    in_check = is_in_check(board, side)
    if is_checkmate(board, side):
        return {"status": "checkmate", "winner": other_side(side), "in_check": True}
    if is_stalemate(board, side):
        return {"status": "stalemate", "winner": other_side(side), "in_check": False}
    return {"status": "ongoing", "winner": None, "in_check": in_check}
