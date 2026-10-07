"""Legal move generation, attack detection, and check/checkmate for Xiangqi."""
from __future__ import annotations

from .board import RED, BLACK, Board, Move, other_side, piece_color

PALACE_COLS = {3, 4, 5}
RED_PALACE_ROWS = {7, 8, 9}
BLACK_PALACE_ROWS = {0, 1, 2}
RED_HALF = set(range(5, 10))
BLACK_HALF = set(range(0, 5))

HORSE_STEPS = [
    ((-2, -1), (-1, 0)), ((-2, 1), (-1, 0)),
    ((2, -1), (1, 0)), ((2, 1), (1, 0)),
    ((-1, -2), (0, -1)), ((1, -2), (0, -1)),
    ((-1, 2), (0, 1)), ((1, 2), (0, 1)),
]

ELEPHANT_STEPS = [(-2, -2), (-2, 2), (2, -2), (2, 2)]
ADVISOR_STEPS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
ORTHO_STEPS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _palace_rows(side: str) -> set[int]:
    return RED_PALACE_ROWS if side == RED else BLACK_PALACE_ROWS


def _own_half(side: str) -> set[int]:
    return RED_HALF if side == RED else BLACK_HALF


def piece_pseudo_moves(board: Board, sq: tuple[int, int]) -> list[tuple[int, int]]:
    """All pseudo-legal destination squares for the piece at sq (ignores whether
    the moving side's own general would be left in check)."""
    r, c = sq
    piece = board.grid[r][c]
    if piece is None:
        return []
    side = piece_color(piece)
    kind = piece.upper()
    dests: list[tuple[int, int]] = []

    def own(dr, dc):
        p = board.piece_at((dr, dc))
        return p is not None and piece_color(p) == side

    def enemy(dr, dc):
        p = board.piece_at((dr, dc))
        return p is not None and piece_color(p) != side

    if kind == "K":
        for dr, dc in ORTHO_STEPS:
            nr, nc = r + dr, c + dc
            if nc in PALACE_COLS and nr in _palace_rows(side) and not own(nr, nc):
                dests.append((nr, nc))
    elif kind == "A":
        for dr, dc in ADVISOR_STEPS:
            nr, nc = r + dr, c + dc
            if nc in PALACE_COLS and nr in _palace_rows(side) and not own(nr, nc):
                dests.append((nr, nc))
    elif kind == "B":
        for dr, dc in ELEPHANT_STEPS:
            nr, nc = r + dr, c + dc
            eye = (r + dr // 2, c + dc // 2)
            if not board.in_bounds((nr, nc)):
                continue
            if nr not in _own_half(side):
                continue
            if board.piece_at(eye) is not None:
                continue
            if own(nr, nc):
                continue
            dests.append((nr, nc))
    elif kind == "N":
        for (dr, dc), (lr, lc) in HORSE_STEPS:
            leg = (r + lr, c + lc)
            nr, nc = r + dr, c + dc
            if not board.in_bounds((nr, nc)):
                continue
            if board.piece_at(leg) is not None:
                continue
            if own(nr, nc):
                continue
            dests.append((nr, nc))
    elif kind == "R":
        for dr, dc in ORTHO_STEPS:
            nr, nc = r + dr, c + dc
            while board.in_bounds((nr, nc)):
                p = board.piece_at((nr, nc))
                if p is None:
                    dests.append((nr, nc))
                else:
                    if piece_color(p) != side:
                        dests.append((nr, nc))
                    break
                nr += dr
                nc += dc
    elif kind == "C":
        for dr, dc in ORTHO_STEPS:
            nr, nc = r + dr, c + dc
            screened = False
            while board.in_bounds((nr, nc)):
                p = board.piece_at((nr, nc))
                if not screened:
                    if p is None:
                        dests.append((nr, nc))
                    else:
                        screened = True
                else:
                    if p is not None:
                        if piece_color(p) != side:
                            dests.append((nr, nc))
                        break
                nr += dr
                nc += dc
    elif kind == "P":
        fwd = -1 if side == RED else 1
        nr, nc = r + fwd, c
        if board.in_bounds((nr, nc)) and not own(nr, nc):
            dests.append((nr, nc))
        crossed = (side == RED and r <= 4) or (side == BLACK and r >= 5)
        if crossed:
            for dc in (-1, 1):
                nr2, nc2 = r, c + dc
                if board.in_bounds((nr2, nc2)) and not own(nr2, nc2):
                    dests.append((nr2, nc2))

    return dests


def is_square_attacked(board: Board, sq: tuple[int, int], by_side: str) -> bool:
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is not None and piece_color(p) == by_side:
                if sq in piece_pseudo_moves(board, (r, c)):
                    return True
    return False


def is_in_check(board: Board, side: str) -> bool:
    gsq = board.find_general(side)
    if gsq is None:
        return True
    return is_square_attacked(board, gsq, other_side(side))


def pseudo_legal_moves(board: Board, side: str) -> list[Move]:
    moves = []
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is not None and piece_color(p) == side:
                for dest in piece_pseudo_moves(board, (r, c)):
                    moves.append(Move((r, c), dest))
    return moves


def legal_moves(board: Board, side: str | None = None) -> list[Move]:
    side = side or board.side_to_move
    legal = []
    for mv in pseudo_legal_moves(board, side):
        board.apply_move(mv)
        illegal = is_in_check(board, side) or board.generals_facing()
        board.undo_move()
        if not illegal:
            legal.append(mv)
    return legal


def is_checkmate(board: Board, side: str | None = None) -> bool:
    side = side or board.side_to_move
    if not is_in_check(board, side):
        return False
    return len(legal_moves(board, side)) == 0


def is_stalemate(board: Board, side: str | None = None) -> bool:
    side = side or board.side_to_move
    if is_in_check(board, side):
        return False
    return len(legal_moves(board, side)) == 0
