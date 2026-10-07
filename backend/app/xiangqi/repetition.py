"""重复局面判定 — Chinese-rules handling of repeated positions.

Under Chinese (中国象棋) rules a repetition is NOT automatically a draw the way
it is in international chess. The side that forces the repetition by checking
every time is judged the loser (长将判负). Only a repetition that neither side
is forcing with checks is a draw.

Scope
-----
Implemented: 长将 (perpetual check) and the plain repetition draw.

NOT implemented: 长捉 (perpetual chasing of an unprotected piece) and 长兑
(perpetual offering of exchanges). Deciding those correctly requires judging
whether a chased piece is "protected" and whether a chase is a genuine threat —
rules with many special cases (e.g. pawns that have crossed the river, chases
by a general or pawn being exempt) where a naive implementation would confidently
give wrong verdicts. Such games are reported as a repetition draw instead.
"""
from __future__ import annotations

from dataclasses import dataclass

from .board import BLACK, RED

# How many times a position must appear before the repetition rules apply.
REPETITION_LIMIT = 3


@dataclass
class RepetitionVerdict:
    status: str  # "draw_repetition" | "perpetual_loss"
    winner: str | None
    note: str
    perpetual_side: str | None = None


def _side_label(side: str) -> str:
    return "红方" if side == RED else "黑方"


def evaluate_repetition(
    position_keys: list[str],
    move_sides: list[str],
    move_gave_check: list[bool],
) -> RepetitionVerdict | None:
    """Judge the current position for repetition.

    `position_keys` holds the key of every position including the starting one,
    so it is one longer than the per-move lists. `move_sides[i]` is the side
    that played ply i and `move_gave_check[i]` whether that ply gave check.

    Returns None when the current position is not yet a repetition.
    """
    if not position_keys:
        return None

    current = position_keys[-1]
    occurrences = [i for i, key in enumerate(position_keys) if key == current]
    if len(occurrences) < REPETITION_LIMIT:
        return None

    # Plies inside the repeating cycle: everything after the first occurrence.
    first = occurrences[0]
    cycle = range(first, len(move_sides))

    checking_sides = []
    for side in (RED, BLACK):
        side_plies = [i for i in cycle if move_sides[i] == side]
        if side_plies and all(move_gave_check[i] for i in side_plies):
            checking_sides.append(side)

    if len(checking_sides) == 1:
        loser = checking_sides[0]
        winner = BLACK if loser == RED else RED
        return RepetitionVerdict(
            status="perpetual_loss",
            winner=winner,
            perpetual_side=loser,
            note=f"{_side_label(loser)}长将，按中国象棋规则判负，{_side_label(winner)}胜。",
        )

    if len(checking_sides) == 2:
        return RepetitionVerdict(
            status="draw_repetition",
            winner=None,
            note="双方均为长将，按规则判和。",
        )

    return RepetitionVerdict(
        status="draw_repetition",
        winner=None,
        note="局面三次重复，双方均未长将，判和。",
    )


def repetition_warning(
    position_keys: list[str],
    move_sides: list[str],
    move_gave_check: list[bool],
) -> str | None:
    """Warn while a perpetual-check pattern is forming but before it is judged,
    so the player can steer away rather than be surprised by the verdict."""
    if not position_keys:
        return None
    current = position_keys[-1]
    occurrences = [i for i, key in enumerate(position_keys) if key == current]
    if not 2 <= len(occurrences) < REPETITION_LIMIT:
        return None

    first = occurrences[0]
    cycle = range(first, len(move_sides))
    for side in (RED, BLACK):
        side_plies = [i for i in cycle if move_sides[i] == side]
        if side_plies and all(move_gave_check[i] for i in side_plies):
            return (
                f"注意：局面已重复，{_side_label(side)}正在连续将军。"
                f"再重复一次将按长将判负。"
            )
    return "注意：局面已经重复出现，再重复一次将按和棋处理。"
