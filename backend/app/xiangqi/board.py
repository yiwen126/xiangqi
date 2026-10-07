"""Xiangqi board representation.

Internal coordinates: (row, col), row 0..9 top-to-bottom, col 0..8 left-to-right.
Row 0 is black's back rank (matches FEN rank order top-to-bottom).
Row 9 is red's back rank.
Piece letters follow the common Xiangqi FEN convention (same as Pikafish/UCCI):
  K/k = general, A/a = advisor, B/b = elephant, N/n = horse,
  R/r = chariot, C/c = cannon, P/p = pawn.
Uppercase = red, lowercase = black.
"""
from __future__ import annotations

from dataclasses import dataclass, field

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"

RED = "w"
BLACK = "b"


def piece_color(piece: str) -> str:
    return RED if piece.isupper() else BLACK


def other_side(side: str) -> str:
    return BLACK if side == RED else RED


@dataclass
class Move:
    from_sq: tuple[int, int]
    to_sq: tuple[int, int]

    def to_uci(self) -> str:
        f_col, f_row = self.from_sq[1], self.from_sq[0]
        t_col, t_row = self.to_sq[1], self.to_sq[0]
        return (
            f"{chr(ord('a') + f_col)}{9 - f_row}"
            f"{chr(ord('a') + t_col)}{9 - t_row}"
        )

    @staticmethod
    def from_uci(uci: str) -> "Move":
        f_col = ord(uci[0]) - ord("a")
        f_row = 9 - int(uci[1])
        t_col = ord(uci[2]) - ord("a")
        t_row = 9 - int(uci[3])
        return Move((f_row, f_col), (t_row, t_col))


@dataclass
class UndoInfo:
    move: Move
    captured: str | None
    prev_side: str
    prev_halfmove_clock: int = 0
    prev_fullmove_number: int = 1


@dataclass
class Board:
    grid: list[list[str | None]] = field(default_factory=lambda: [[None] * 9 for _ in range(10)])
    side_to_move: str = RED
    history: list[UndoInfo] = field(default_factory=list)
    # Plies since the last capture, and the 1-based move number (incremented
    # after each black move). Real values matter because they are handed to the
    # engine in the FEN.
    halfmove_clock: int = 0
    fullmove_number: int = 1

    @classmethod
    def from_fen(cls, fen: str = START_FEN) -> "Board":
        board = cls()
        parts = fen.strip().split()
        rows = parts[0].split("/")
        if len(rows) != 10:
            raise ValueError(f"invalid FEN, expected 10 ranks: {fen}")
        for r, row_str in enumerate(rows):
            c = 0
            for ch in row_str:
                if ch.isdigit():
                    c += int(ch)
                else:
                    board.grid[r][c] = ch
                    c += 1
            if c != 9:
                raise ValueError(f"invalid FEN rank length: {row_str}")
        board.side_to_move = RED if len(parts) < 2 or parts[1] == "w" else BLACK
        if len(parts) >= 5:
            try:
                board.halfmove_clock = int(parts[4])
            except ValueError:
                board.halfmove_clock = 0
        if len(parts) >= 6:
            try:
                board.fullmove_number = int(parts[5])
            except ValueError:
                board.fullmove_number = 1
        return board

    def to_fen(self) -> str:
        rows = []
        for r in range(10):
            row_str = ""
            empty = 0
            for c in range(9):
                p = self.grid[r][c]
                if p is None:
                    empty += 1
                else:
                    if empty:
                        row_str += str(empty)
                        empty = 0
                    row_str += p
            if empty:
                row_str += str(empty)
            rows.append(row_str)
        board_part = "/".join(rows)
        side = "w" if self.side_to_move == RED else "b"
        return f"{board_part} {side} - - {self.halfmove_clock} {self.fullmove_number}"

    def position_key(self) -> str:
        """Identity of a position for repetition purposes: placement plus side
        to move. Move counters are deliberately excluded — a position repeats
        regardless of how many moves it took to get back to it."""
        return self.to_fen().rsplit(" ", 2)[0]

    def clone(self) -> "Board":
        b = Board()
        b.grid = [row[:] for row in self.grid]
        b.side_to_move = self.side_to_move
        b.history = list(self.history)
        b.halfmove_clock = self.halfmove_clock
        b.fullmove_number = self.fullmove_number
        return b

    def piece_at(self, sq: tuple[int, int]) -> str | None:
        r, c = sq
        if 0 <= r < 10 and 0 <= c < 9:
            return self.grid[r][c]
        return None

    def in_bounds(self, sq: tuple[int, int]) -> bool:
        r, c = sq
        return 0 <= r < 10 and 0 <= c < 9

    def find_general(self, side: str) -> tuple[int, int] | None:
        target = "K" if side == RED else "k"
        for r in range(10):
            for c in range(9):
                if self.grid[r][c] == target:
                    return (r, c)
        return None

    def apply_move(self, move: Move) -> UndoInfo:
        fr, fc = move.from_sq
        tr, tc = move.to_sq
        captured = self.grid[tr][tc]
        undo = UndoInfo(
            move=move,
            captured=captured,
            prev_side=self.side_to_move,
            prev_halfmove_clock=self.halfmove_clock,
            prev_fullmove_number=self.fullmove_number,
        )
        self.grid[tr][tc] = self.grid[fr][fc]
        self.grid[fr][fc] = None
        self.halfmove_clock = 0 if captured is not None else self.halfmove_clock + 1
        if self.side_to_move == BLACK:
            self.fullmove_number += 1
        self.side_to_move = other_side(self.side_to_move)
        self.history.append(undo)
        return undo

    def undo_move(self) -> None:
        undo = self.history.pop()
        fr, fc = undo.move.from_sq
        tr, tc = undo.move.to_sq
        self.grid[fr][fc] = self.grid[tr][tc]
        self.grid[tr][tc] = undo.captured
        self.side_to_move = undo.prev_side
        self.halfmove_clock = undo.prev_halfmove_clock
        self.fullmove_number = undo.prev_fullmove_number

    def generals_facing(self) -> bool:
        """True if the two generals are on the same file with nothing between them
        (the 'flying general' condition — illegal for the side that just moved)."""
        rk = self.find_general(RED)
        bk = self.find_general(BLACK)
        if rk is None or bk is None:
            return False
        if rk[1] != bk[1]:
            return False
        col = rk[1]
        lo, hi = sorted([rk[0], bk[0]])
        for r in range(lo + 1, hi):
            if self.grid[r][col] is not None:
                return False
        return True
