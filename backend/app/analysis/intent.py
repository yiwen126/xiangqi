"""Rule-based move-intent detection: what a move attacked or saved.

Pure board analysis — no engine calls, no I/O, no notation. Like ``tactics.py``
this module returns facts; ``explain.py`` turns them into Chinese.

The scope is deliberately narrow: only changes the move actually caused are
reported (an attack that already existed before the move is never re-announced),
and only when the exchange is real — a "pressure" row that fires on every quiet
move is noise an experienced player ignores.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..xiangqi.board import Board, Move, other_side, piece_color
from ..xiangqi.movegen import is_in_check
from .tactics import (
    SEE_REPORT_THRESHOLD,
    attackers_of,
    capture_is_legal,
    defenders_of,
    piece_value,
    static_exchange_eval,
)

# An even exchange offer is only worth a row when the victim is worth at least
# a horse: poking an advisor or a pawn is ordinary play.
ATTACK_EVEN_MIN_VALUE = 4.0
# Saving a pawn is never worth reporting.
DEFEND_MIN_VALUE = 2.0
# How many 攻/守 rows the coach will show (applied by `detect`).
MAX_ATTACK_ROWS = 2
MAX_DEFEND_ROWS = 2


@dataclass
class IntentTag:
    kind: str  # "attack" | "defend"
    piece: str
    piece_sq: tuple[int, int]
    target_sqs: list[tuple[int, int]] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def _legal_attackers(board: Board, sq: tuple[int, int], side: str) -> list[tuple[int, int]]:
    """`side` pieces that can actually capture on `sq`: a pinned attacker is
    not a real threat."""
    return [a for a in attackers_of(board, sq, side) if capture_is_legal(board, a, sq)]


def new_attacks(board_before: Board, board_after: Board, move: Move) -> list[IntentTag]:
    """Attacks the move newly created, one tag per victim, in scan order.

    The victim must be an enemy piece that is still on the board (the piece the
    move captured is gone), so a capturing move never names what it just ate.

    Triggers are "the move started attacking a square that had no legal
    attacker before" or "the square became winnable"; a pre-existing contact
    that was and remains winnable is not this move's doing. Tier `win` needs a
    forced net gain (SEE), `even` covers a defended piece worth at least a
    horse attacked by a piece no more valuable than it — an exchange offer or
    a standoff that is still pressure, never worded as a threat.
    """
    mover = piece_color(board_after.piece_at(move.to_sq))
    tags: list[IntentTag] = []

    for r in range(10):
        for c in range(9):
            victim = board_after.grid[r][c]
            if victim is None or victim.upper() == "K" or piece_color(victim) == mover:
                continue
            sq = (r, c)

            attackers = _legal_attackers(board_after, sq, mover)
            if not attackers:
                continue
            see_after = static_exchange_eval(board_after, sq, mover)
            see_before = static_exchange_eval(board_before, sq, mover)
            newly_contacted = not _legal_attackers(board_before, sq, mover)
            newly_winnable = see_before < SEE_REPORT_THRESHOLD <= see_after
            if not (newly_contacted or newly_winnable):
                continue

            # Credit the moved piece when it is one of the attackers, else the
            # cheapest one — the piece that would actually start the trade.
            attacker_sq = move.to_sq if move.to_sq in attackers else min(
                attackers, key=lambda a: piece_value(board_after.piece_at(a))
            )
            attacker = board_after.piece_at(attacker_sq)
            victim_value = piece_value(victim)
            if see_after >= SEE_REPORT_THRESHOLD:
                tier = "win"
            elif victim_value >= ATTACK_EVEN_MIN_VALUE and victim_value >= piece_value(attacker):
                tier = "even"
            else:
                continue

            tags.append(IntentTag(
                kind="attack",
                piece=attacker,
                piece_sq=attacker_sq,
                target_sqs=[sq],
                detail={
                    "tier": tier,
                    "see": see_after,
                    "defended": bool(defenders_of(board_after, sq, other_side(mover))),
                },
            ))

    return tags


def saved_pieces(board_before: Board, board_after: Board, move: Move) -> list[IntentTag]:
    """Defenses the move performed, one tag per own piece it rescued, in scan order.

    A piece is saved when the opponent could force a real loss on its square
    before the move and cannot after. The mover itself is the `escape` case:
    its after square is the destination, while `piece_sq` stays the origin
    square so the wording can say what left where. The named threat is the
    cheapest legal attacker on the before board — the piece that would
    actually start the trade — and `threat_uci` is its capture, kept even when
    the move captured that attacker, because the reason still is the threat.

    Suppressed when the move gives check: SEE cannot judge the opponent's
    captures while they are in check, so it would read every threat as gone and
    report a still-lost piece as saved. Defense claims are the only casualty —
    attack detection is unaffected, since our own captures stay legal.
    """
    mover = piece_color(board_before.piece_at(move.from_sq))
    opponent = other_side(mover)
    if is_in_check(board_after, opponent):
        # SEE cannot judge threats while the opponent is in check: every capture
        # they could make is legally blocked by the check, so see_after reads 0
        # and a still-lost piece would be reported as saved. Stay silent instead.
        return []
    tags: list[IntentTag] = []

    for r in range(10):
        for c in range(9):
            piece = board_before.grid[r][c]
            if piece is None or piece_color(piece) != mover or piece.upper() == "K":
                continue
            if piece_value(piece) < DEFEND_MIN_VALUE:
                continue
            sq = (r, c)
            see_before = static_exchange_eval(board_before, sq, opponent)
            if see_before < SEE_REPORT_THRESHOLD:
                continue

            see_after = static_exchange_eval(
                board_after, move.to_sq if sq == move.from_sq else sq, opponent
            )
            if see_after >= SEE_REPORT_THRESHOLD:
                continue  # still losable — the move did not really save it

            primary = min(
                _legal_attackers(board_before, sq, opponent),
                key=lambda a: piece_value(board_before.piece_at(a)),
            )
            tags.append(IntentTag(
                kind="defend",
                piece=piece,
                piece_sq=sq,
                target_sqs=[primary],
                detail={
                    "escape": sq == move.from_sq,
                    "see_before": see_before,
                    "threat_uci": Move(primary, sq).to_uci(),
                },
            ))

    return tags


def detect(board: Board, move: Move) -> list[IntentTag]:
    """Every intent tag for `move`: what it attacked, then what it saved.

    Attacks come first, winners before even offers and the biggest victim
    first within each tier; defenses follow, the largest saved loss first.
    Pure and deterministic — no engine, no I/O — and the caller's board is
    never mutated.
    """
    before = board.clone()
    after = board.clone()
    after.apply_move(move)

    attacks = new_attacks(before, after, move)
    # Over the cap, name the chariot rather than the horse.
    attacks.sort(key=lambda t: (
        0 if t.detail["tier"] == "win" else 1,
        -piece_value(after.piece_at(t.target_sqs[0])),
    ))
    defenses = saved_pieces(before, after, move)
    defenses.sort(key=lambda t: -t.detail["see_before"])
    return attacks[:MAX_ATTACK_ROWS] + defenses[:MAX_DEFEND_ROWS]
