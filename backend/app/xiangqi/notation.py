"""中文记谱法 — traditional Chinese Xiangqi move notation.

Converts a (board, move) pair into standard notation such as 炮二平五,
马八进七, 车九平八, 前马进七.

File numbering
--------------
Files are counted from each side's OWN right, so the two sides number the
board in opposite directions:

* RED   uses Chinese numerals 一二三四五六七八九, file = ``9 - col``
  (col 8 = 一路 … col 0 = 九路).
* BLACK uses full-width Arabic numerals １２３４５６７８９, file = ``col + 1``
  (col 0 = １路 … col 8 = ９路).

Move form
---------
``<piece><origin-file><action><number>``

* 平 — the move stays on the same rank; ``number`` is the DESTINATION file.
* 进 — the move goes toward the opponent; 退 — away from them.
  - For straight-line movers (车 炮 兵/卒 将/帅) ``number`` is the COUNT OF
    RANKS travelled.
  - For the diagonal/L movers (马 相/象 仕/士) a rank count would be
    ambiguous, so ``number`` is the DESTINATION file instead.

Disambiguation
--------------
When two or more identical pieces stand on the same file the origin file
cannot identify which one moved, so a positional prefix replaces it:

* 2 pieces — 前 / 后
* 3 pieces — 前 / 中 / 后
* 4+ pieces — positional numerals counted from the front (一二三四五 / １２３４５)

"Front" always means nearer the opponent from the moving side's point of view.
If more than one file carries such a stack of the same piece the prefix alone
is still ambiguous, so the origin file is kept as well (e.g. 前兵三进一).
"""
from __future__ import annotations

from .board import RED, Board, Move, piece_color

RED_NUMERALS = "一二三四五六七八九"
BLACK_NUMERALS = "１２３４５６７８９"

# Standard notation names. Red and black share 马/车/炮 (the decorative
# 傌/俥/砲 variants are a board-display convention, not a notation one) and are
# told apart by 帅/将, 仕/士, 相/象, 兵/卒.
NOTATION_NAMES = {
    "K": "帅", "k": "将",
    "A": "仕", "a": "士",
    "B": "相", "b": "象",
    "N": "马", "n": "马",
    "R": "车", "r": "车",
    "C": "炮", "c": "炮",
    "P": "兵", "p": "卒",
}

# Pieces whose vertical moves are written as a count of ranks travelled.
STRAIGHT_MOVERS = {"K", "R", "C", "P"}


def file_number(col: int, side: str) -> int:
    """1-9 file number of `col` from `side`'s own perspective."""
    return 9 - col if side == RED else col + 1


def numeral(n: int, side: str) -> str:
    """Render 1-9 in the numeral system the given side uses."""
    if not 1 <= n <= 9:
        raise ValueError(f"numeral out of range: {n}")
    return (RED_NUMERALS if side == RED else BLACK_NUMERALS)[n - 1]


def _is_forward(dr: int, side: str) -> bool:
    """True if a row delta moves toward the opponent. Red sits on row 9 and
    advances toward row 0; black is the mirror image."""
    return dr < 0 if side == RED else dr > 0


def _stack_on_file(board: Board, col: int, piece: str) -> list[int]:
    """Rows of every identical piece (same type AND colour) on `col`,
    ordered front-to-back from the owning side's perspective."""
    rows = [r for r in range(10) if board.grid[r][col] == piece]
    return sorted(rows) if piece_color(piece) == RED else sorted(rows, reverse=True)


def _positional_prefix(board: Board, from_sq: tuple[int, int], piece: str) -> tuple[str | None, bool]:
    """Return (prefix, keep_origin_file) for a piece that shares its file with
    identical pieces. prefix is None when no disambiguation is needed."""
    row, col = from_sq
    side = piece_color(piece)
    stack = _stack_on_file(board, col, piece)
    if len(stack) < 2:
        return None, False

    idx = stack.index(row)
    count = len(stack)
    if count == 2:
        prefix = "前" if idx == 0 else "后"
    elif count == 3:
        prefix = ("前", "中", "后")[idx]
    else:
        prefix = numeral(idx + 1, side)

    # If several files each carry a stack of this same piece, the prefix alone
    # does not say WHICH file, so the origin file has to stay.
    stacked_files = sum(
        1 for c in range(9)
        if sum(1 for r in range(10) if board.grid[r][c] == piece) >= 2
    )
    return prefix, stacked_files > 1


def move_to_chinese(board: Board, move: Move) -> str:
    """Render `move` in Chinese notation. `board` must be the position BEFORE
    the move is applied."""
    piece = board.piece_at(move.from_sq)
    if piece is None:
        raise ValueError(f"no piece at {move.from_sq} to move")

    side = piece_color(piece)
    name = NOTATION_NAMES[piece]
    (from_row, from_col), (to_row, to_col) = move.from_sq, move.to_sq
    dr = to_row - from_row

    if dr == 0:
        action = "平"
        trailing = file_number(to_col, side)
    else:
        action = "进" if _is_forward(dr, side) else "退"
        if piece.upper() in STRAIGHT_MOVERS:
            trailing = abs(dr)
        else:
            trailing = file_number(to_col, side)

    prefix, keep_file = _positional_prefix(board, move.from_sq, piece)
    origin = numeral(file_number(from_col, side), side)
    tail = f"{action}{numeral(trailing, side)}"

    if prefix is None:
        return f"{name}{origin}{tail}"
    if keep_file:
        return f"{prefix}{name}{origin}{tail}"
    return f"{prefix}{name}{tail}"


def moves_to_chinese(board: Board, uci_moves: list[str]) -> list[str]:
    """Render a sequence of UCI moves (e.g. an engine PV) in Chinese notation,
    replaying them on a scratch copy of `board`. Stops early if the sequence
    desynchronises from the position rather than raising, since engine PVs are
    advisory and may run past a position we can reconstruct."""
    scratch = board.clone()
    out: list[str] = []
    for uci in uci_moves:
        try:
            move = Move.from_uci(uci)
        except (ValueError, IndexError):
            break
        if scratch.piece_at(move.from_sq) is None:
            break
        out.append(move_to_chinese(scratch, move))
        scratch.apply_move(move)
    return out


def chinese_to_move(board: Board, text: str, side: str | None = None) -> Move:
    """Parse Chinese notation back into a move by finding the one legal move
    that renders as `text`. Raises if nothing matches, or if the notation is
    ambiguous — which would mean move_to_chinese had produced a name that does
    not uniquely identify a move.
    """
    from .movegen import legal_moves  # local import: movegen has no notation dep

    side = side or board.side_to_move
    matches = [mv for mv in legal_moves(board, side) if move_to_chinese(board, mv) == text]
    if not matches:
        raise ValueError(f"no legal move matches notation {text!r}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous notation {text!r}: {[m.to_uci() for m in matches]}")
    return matches[0]


def square_to_chinese(sq: tuple[int, int], side: str) -> str:
    """Describe a square as a file from `side`'s perspective, e.g. 三路.
    Used to phrase coaching text in the same terms as the notation."""
    return f"{numeral(file_number(sq[1], side), side)}路"
