"""Rule-based tactical pattern detectors.

Each detector is a pure function of board state returning TacticTag objects that
explain.py turns into Chinese teaching text. No engine calls, no LLM calls —
fully deterministic.

Detection is deliberately CONSERVATIVE. An experienced player is not helped by
being told that two pawns face each other; a warning that fires on every move
is noise they will learn to ignore. So captures are scored with a real static
exchange evaluation (SEE) and only reported when the exchange actually loses
material, and pins are only reported when the restriction is materially real.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..xiangqi.board import RED, Board, Move, other_side, piece_color
from ..xiangqi.movegen import (
    ADVISOR_STEPS,
    ELEPHANT_STEPS,
    HORSE_STEPS,
    ORTHO_STEPS,
    is_in_check,
    piece_pseudo_moves,
)

PIECE_NAMES = {
    "K": "帅", "k": "将",
    "A": "仕", "a": "士",
    "B": "相", "b": "象",
    "N": "马", "n": "马",
    "R": "车", "r": "车",
    "C": "炮", "c": "炮",
    "P": "兵", "p": "卒",
}

# Rough Xiangqi material values in "pawn units". The general is given a value
# far above everything else so SEE never trades it away.
PIECE_VALUES = {"K": 1000.0, "A": 2.0, "B": 2.0, "N": 4.0, "R": 9.0, "C": 4.5, "P": 1.0}

# Losing this much material (in pawn units) in a forced exchange is worth
# mentioning. Set above a single pawn on purpose: mutual pawn tension (兵七进一
# facing 卒７进１) is ordinary opening play, and reporting it on every move is
# exactly the noise that made the old detector useless. Losing an
# advisor/elephant (2.0) or more still reports.
SEE_REPORT_THRESHOLD = 1.5


def piece_name(piece: str) -> str:
    return PIECE_NAMES.get(piece, piece)


def piece_value(piece: str) -> float:
    return PIECE_VALUES.get(piece.upper(), 0.0)


def sq_name(sq: tuple[int, int]) -> str:
    r, c = sq
    return f"{chr(ord('a') + c)}{9 - r}"


@dataclass
class TacticTag:
    kind: str  # "hanging" | "fork" | "pin" | "cannon_threat" | "hollow_cannon"
    side: str  # side that benefits from this tactic (the attacker), RED/BLACK
    piece_sq: tuple[int, int]
    piece: str
    target_sqs: list[tuple[int, int]] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def attackers_of(board: Board, sq: tuple[int, int], by_side: str) -> list[tuple[int, int]]:
    """Squares holding a `by_side` piece that pseudo-attacks `sq`.

    Walks outward from `sq` instead of scanning all 90 squares, which matters
    because SEE calls this repeatedly.
    """
    r, c = sq
    found: list[tuple[int, int]] = []

    # Chariots (first piece along a ray) and cannons (first piece BEHIND a screen).
    for dr, dc in ORTHO_STEPS:
        nr, nc = r + dr, c + dc
        screen = None
        while 0 <= nr < 10 and 0 <= nc < 9:
            p = board.grid[nr][nc]
            if p is not None:
                screen = (nr, nc, p)
                break
            nr, nc = nr + dr, nc + dc
        if screen is None:
            continue
        sr, sc, sp = screen
        if piece_color(sp) == by_side and sp.upper() == "R":
            found.append((sr, sc))
        # The general attacks an orthogonally adjacent square.
        if piece_color(sp) == by_side and sp.upper() == "K" and abs(sr - r) + abs(sc - c) == 1:
            found.append((sr, sc))
        nr, nc = sr + dr, sc + dc
        while 0 <= nr < 10 and 0 <= nc < 9:
            p = board.grid[nr][nc]
            if p is not None:
                if piece_color(p) == by_side and p.upper() == "C":
                    found.append((nr, nc))
                break
            nr, nc = nr + dr, nc + dc

    # Step/leap pieces: their move patterns are symmetric, so candidate origin
    # squares are just `sq` offset by the same deltas. Confirm with the real
    # generator so blocked horse legs and elephant eyes are respected.
    candidates: list[tuple[int, int]] = []
    candidates += [(r + dr, c + dc) for dr, dc in [d for d, _ in HORSE_STEPS]]
    candidates += [(r + dr, c + dc) for dr, dc in ELEPHANT_STEPS]
    candidates += [(r + dr, c + dc) for dr, dc in ADVISOR_STEPS]
    candidates += [(r + dr, c + dc) for dr, dc in ORTHO_STEPS]  # pawns
    for cand in candidates:
        if not board.in_bounds(cand):
            continue
        p = board.piece_at(cand)
        if p is None or piece_color(p) != by_side:
            continue
        if p.upper() in ("R", "C", "K"):
            continue  # already handled by the ray walk
        if sq in piece_pseudo_moves(board, cand):
            found.append(cand)

    return list(dict.fromkeys(found))


def capture_is_legal(board: Board, frm: tuple[int, int], to: tuple[int, int]) -> bool:
    """Whether `frm`->`to` can actually be played (does not expose its own
    general). A pinned attacker is not a real threat."""
    piece = board.piece_at(frm)
    if piece is None:
        return False
    side = piece_color(piece)
    board.apply_move(Move(frm, to))
    bad = is_in_check(board, side) or board.generals_facing()
    board.undo_move()
    return not bad


def static_exchange_eval(board: Board, sq: tuple[int, int], side: str) -> float:
    """Material `side` wins by starting a capture sequence on `sq`, assuming
    both sides recapture with their least valuable piece and either may stop
    when continuing would lose material.

    Legality is enforced for the first capture only; deeper recaptures use
    pseudo-attackers, the standard engine approximation.
    """
    victim = board.piece_at(sq)
    if victim is None or piece_color(victim) == side:
        return 0.0

    attackers = [a for a in attackers_of(board, sq, side) if capture_is_legal(board, a, sq)]
    if not attackers:
        return 0.0
    return _see_recurse(board, sq, side, attackers)


def _see_recurse(board: Board, sq: tuple[int, int], side: str, attackers: list[tuple[int, int]]) -> float:
    victim = board.piece_at(sq)
    if victim is None or not attackers:
        return 0.0
    attacker = min(attackers, key=lambda a: piece_value(board.piece_at(a)))
    gain = piece_value(victim)

    nxt = board.clone()
    nxt.grid[sq[0]][sq[1]] = nxt.grid[attacker[0]][attacker[1]]
    nxt.grid[attacker[0]][attacker[1]] = None
    # Re-scanning from the new position picks up x-ray attackers (doubled
    # chariots, a cannon that just gained its screen) automatically.
    opp = other_side(side)
    reply = attackers_of(nxt, sq, opp)
    # Either side may stand pat rather than continue a losing exchange.
    return max(0.0, gain - _see_recurse(nxt, sq, opp, reply))


def find_hanging_pieces(board: Board, side: str) -> list[TacticTag]:
    """Pieces of `side` that the opponent can profitably win by force."""
    tags = []
    opp = other_side(side)
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is None or piece_color(p) != side or p.upper() == "K":
                continue
            sq = (r, c)
            loss = static_exchange_eval(board, sq, opp)
            if loss < SEE_REPORT_THRESHOLD:
                continue
            attackers = [a for a in attackers_of(board, sq, opp) if capture_is_legal(board, a, sq)]
            defenders = defenders_of(board, sq, side)
            tags.append(TacticTag(
                kind="hanging", side=opp, piece_sq=sq, piece=p,
                target_sqs=attackers,
                detail={"defended": bool(defenders), "value": piece_value(p), "see_loss": round(loss, 1)},
            ))
    return tags


def defenders_of(board: Board, sq: tuple[int, int], defending_side: str) -> list[tuple[int, int]]:
    """Defenders of a square occupied by defending_side's own piece: swap in an
    enemy placeholder so jump/slide patterns (notably the cannon's screen
    requirement) resolve the same way they would after a capture."""
    clone = board.clone()
    clone.grid[sq[0]][sq[1]] = "p" if defending_side == RED else "P"
    return attackers_of(clone, sq, defending_side)


def find_forks(board: Board, side: str) -> list[TacticTag]:
    """Pieces of `side` attacking 2+ enemy pieces that cannot all be saved."""
    tags = []
    opp = other_side(side)
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is None or piece_color(p) != side:
                continue
            sq = (r, c)
            targets = []
            for dest in piece_pseudo_moves(board, sq):
                tp = board.grid[dest[0]][dest[1]]
                if tp is None or piece_color(tp) != opp or piece_value(tp) < 2:
                    continue
                # Only count targets actually winnable — a defended piece worth
                # no more than the forking piece is not really forked.
                if static_exchange_eval(board, dest, side) < SEE_REPORT_THRESHOLD:
                    continue
                if not capture_is_legal(board, sq, dest):
                    continue
                targets.append(dest)
            if len(targets) >= 2:
                tags.append(TacticTag(kind="fork", side=side, piece_sq=sq, piece=p, target_sqs=targets))
    return tags


def find_pinned_pieces(board: Board, side: str) -> list[TacticTag]:
    """Pieces of `side` that are genuinely pinned — completely unable to move
    without exposing their own general — and are worth enough to matter.

    The old behaviour flagged any piece with even one restricted move, which
    fired constantly (every piece on the generals' shared file). Only total
    immobility is reported now, and only for pieces of real value.
    """
    tags = []
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is None or piece_color(p) != side or p.upper() == "K":
                continue
            if piece_value(p) < 2:
                continue
            sq = (r, c)
            pseudo = piece_pseudo_moves(board, sq)
            if not pseudo:
                continue
            legal = [d for d in pseudo if capture_is_legal(board, sq, d)]
            if legal:
                continue  # can still move somewhere — not pinned
            # Distinguish a true pin against the general from the flying-general
            # constraint, because the coaching wording differs.
            board.apply_move(Move(sq, pseudo[0]))
            by_facing = board.generals_facing() and not is_in_check(board, side)
            board.undo_move()
            tags.append(TacticTag(
                kind="pin", side=other_side(side), piece_sq=sq, piece=p,
                detail={"by_facing": by_facing, "total_moves": len(pseudo)},
            ))
    return tags


def find_cannon_threats(board: Board, side: str) -> list[TacticTag]:
    """Cannons of `side` that can profitably capture a valuable enemy piece."""
    tags = []
    opp = other_side(side)
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is None or p.upper() != "C" or piece_color(p) != side:
                continue
            sq = (r, c)
            targets = []
            for dest in piece_pseudo_moves(board, sq):
                tp = board.grid[dest[0]][dest[1]]
                if tp is None or piece_color(tp) != opp or piece_value(tp) < 2:
                    continue
                if static_exchange_eval(board, dest, side) < SEE_REPORT_THRESHOLD:
                    continue
                if not capture_is_legal(board, sq, dest):
                    continue
                targets.append(dest)
            if targets:
                tags.append(TacticTag(kind="cannon_threat", side=side, piece_sq=sq, piece=p, target_sqs=targets))
    return tags


def find_hollow_cannon(board: Board, side: str) -> list[TacticTag]:
    """空头炮: a cannon of `side` on the enemy general's file with exactly one
    piece between them — the classic pressure formation."""
    tags = []
    opp = other_side(side)
    gsq = board.find_general(opp)
    if gsq is None:
        return tags
    gr, gc = gsq
    for r in range(10):
        p = board.grid[r][gc]
        if p is None or p.upper() != "C" or piece_color(p) != side:
            continue
        lo, hi = sorted([r, gr])
        between = [board.grid[k][gc] for k in range(lo + 1, hi) if board.grid[k][gc] is not None]
        if len(between) == 1:
            tags.append(TacticTag(kind="hollow_cannon", side=side, piece_sq=(r, gc), piece=p, target_sqs=[gsq]))
    return tags


def all_tactics_for_side(board: Board, side: str) -> list[TacticTag]:
    """Every tactic currently favouring `side`: threats it poses to the
    opponent, plus opponent pieces that are hanging or pinned."""
    tags: list[TacticTag] = []
    tags += find_hanging_pieces(board, other_side(side))
    tags += find_forks(board, side)
    tags += find_pinned_pieces(board, other_side(side))
    tags += find_cannon_threats(board, side)
    tags += find_hollow_cannon(board, side)
    return tags
