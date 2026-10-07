"""中文记谱法 tests.

Notation is the core of the app's teaching value — a wrong name teaches the
wrong move — so this covers every piece type, both colours, 进/退/平, the
前/中/后 disambiguation forms, and a full round-trip over every legal move in a
range of positions.
"""
import pytest

from app.analysis.openings import OPENING_BOOK
from app.xiangqi.board import BLACK, RED, Board, Move
from app.xiangqi.movegen import legal_moves
from app.xiangqi.notation import (
    chinese_to_move,
    file_number,
    move_to_chinese,
    moves_to_chinese,
    numeral,
)


def n(board: Board, uci: str) -> str:
    return move_to_chinese(board, Move.from_uci(uci))


# --------------------------------------------------------------------------
# File numbering: the two sides count from opposite edges.
# --------------------------------------------------------------------------

def test_red_files_counted_from_reds_right():
    # Red's back rank is RNBAKABNR; the general sits on 五路.
    assert file_number(4, RED) == 5
    assert file_number(8, RED) == 1
    assert file_number(0, RED) == 9


def test_black_files_counted_from_blacks_right():
    assert file_number(4, BLACK) == 5
    assert file_number(0, BLACK) == 1
    assert file_number(8, BLACK) == 9


def test_numerals_differ_by_side():
    assert numeral(5, RED) == "五"
    assert numeral(5, BLACK) == "５"
    with pytest.raises(ValueError):
        numeral(0, RED)


# --------------------------------------------------------------------------
# The standard opening moves every player knows by name.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("uci,expected", [
    ("h2e2", "炮二平五"),   # 中炮
    ("b2e2", "炮八平五"),
    ("h2d2", "炮二平六"),   # 过宫炮
    ("b2f2", "炮八平四"),
    ("h2f2", "炮二平四"),   # 士角炮
    ("h2i2", "炮二平一"),   # 边炮
    ("h0g2", "马二进三"),
    ("b0c2", "马八进七"),
    ("c3c4", "兵七进一"),
    ("g3g4", "兵三进一"),
    ("a3a4", "兵九进一"),
    ("i3i4", "兵一进一"),
    ("g0e2", "相三进五"),
    ("c0e2", "相七进五"),
    ("d0e1", "仕六进五"),
    ("f0e1", "仕四进五"),
    ("e0e1", "帅五进一"),
    ("a0a1", "车九进一"),
    ("i0i1", "车一进一"),
])
def test_red_opening_moves(uci, expected):
    assert n(Board.from_fen(), uci) == expected


@pytest.mark.parametrize("uci,expected", [
    ("h9g7", "马８进７"),   # 屏风马
    ("b9c7", "马２进３"),
    ("b9a7", "马２进１"),   # 单提马
    ("h7e7", "炮８平５"),
    ("b7e7", "炮２平５"),
    ("c6c5", "卒３进１"),
    ("g6g5", "卒７进１"),
    ("a9a8", "车１进１"),
    ("i9i8", "车９进１"),
    ("c9e7", "象３进５"),
    ("g9e7", "象７进５"),
    ("d9e8", "士４进５"),
    ("e9e8", "将５进１"),
])
def test_black_opening_moves(uci, expected):
    assert n(Board.from_fen(), uci) == expected


# --------------------------------------------------------------------------
# 进 / 退 / 平 and the rank-count vs destination-file distinction.
# --------------------------------------------------------------------------

def test_straight_movers_count_ranks_travelled():
    # Lone red chariot on a0 (file 九): moving up 3 ranks is 车九进三.
    board = Board.from_fen("3k5/9/9/9/9/9/9/9/9/R3K4 w - - 0 1")
    assert n(board, "a0a3") == "车九进三"


def test_straight_mover_retreat_and_level():
    board = Board.from_fen("3k5/9/9/9/9/R8/9/9/9/4K4 w - - 0 1")
    assert n(board, "a4a1") == "车九退三"
    assert n(board, "a4d4") == "车九平六"


def test_diagonal_movers_name_destination_file():
    # A horse always names the file it lands on, never a rank count.
    board = Board.from_fen("3k5/9/9/9/9/9/9/9/9/4K2N1 w - - 0 1")
    assert n(board, "h0g2") == "马二进三"


def test_black_directions_are_mirrored():
    # Black advances toward larger row indices, so a9->a7 is 进 for black.
    board = Board.from_fen("r2k5/9/9/9/9/9/9/9/9/4K4 b - - 0 1")
    assert n(board, "a9a7") == "车１进２"
    board2 = Board.from_fen("3k5/9/r8/9/9/9/9/9/9/4K4 b - - 0 1")
    assert n(board2, "a7a9") == "车１退２"


# --------------------------------------------------------------------------
# 前 / 中 / 后 disambiguation.
# --------------------------------------------------------------------------

def test_two_pieces_on_a_file_use_front_back():
    board = Board.from_fen("3k5/9/9/9/9/9/9/R8/9/R3K4 w - - 0 1")
    assert n(board, "a2a3") == "前车进一"
    assert n(board, "a0a1") == "后车进一"


def test_three_pawns_on_a_file_use_front_middle_back():
    board = Board.from_fen("3k5/9/9/9/9/P8/P8/P8/9/4K4 w - - 0 1")
    assert n(board, "a4a5") == "前兵进一"
    assert n(board, "a3a4") == "中兵进一"
    assert n(board, "a2a3") == "后兵进一"


def test_four_pieces_on_a_file_use_positional_numerals():
    board = Board.from_fen("3k5/9/9/9/P8/P8/P8/P8/9/4K4 w - - 0 1")
    names = [n(board, u) for u in ("a5a6", "a4a5", "a3a4", "a2a3")]
    assert names == ["一兵进一", "二兵进一", "三兵进一", "四兵进一"]


def test_front_back_keeps_origin_file_when_two_files_are_stacked():
    # 前兵 alone would not say WHICH file, so the file is kept.
    board = Board.from_fen("3k5/9/9/9/9/P1P6/P1P6/9/9/4K4 w - - 0 1")
    assert n(board, "a4a5") == "前兵九进一"
    assert n(board, "c4c5") == "前兵七进一"
    assert n(board, "a3a4") == "后兵九进一"


def test_black_front_is_nearer_red():
    # For black, "front" means the larger row index.
    board = Board.from_fen("3k5/9/9/9/9/9/9/9/4r4/4r4 b - - 0 1")
    assert n(board, "e0e2") == "前车退２"
    assert n(board, "e1e2") == "后车退１"


# --------------------------------------------------------------------------
# Round-trip: notation must uniquely identify one legal move.
# --------------------------------------------------------------------------

ROUND_TRIP_POSITIONS = [
    Board.from_fen().to_fen(),                                        # start
    "3k5/9/9/9/9/P8/P8/P8/9/4K4 w - - 0 1",                           # stacked pawns
    "3k5/9/9/9/9/9/9/R8/9/R3K4 w - - 0 1",                            # doubled chariots
    "r1bakabr1/9/1cn3nc1/p1p1p1p1p/9/9/P1P1P1P1P/1CN3NC1/9/R1BAKABR1 w - - 0 1",
    "2bakab2/9/2n1c1n2/p1p1p1p1p/9/9/P1P1P1P1P/2N1C1N2/9/2BAKAB2 b - - 0 1",
]


@pytest.mark.parametrize("fen", ROUND_TRIP_POSITIONS)
def test_every_legal_move_round_trips(fen):
    board = Board.from_fen(fen)
    moves = legal_moves(board, board.side_to_move)
    assert moves, "position should have legal moves"
    for mv in moves:
        text = move_to_chinese(board, mv)
        decoded = chinese_to_move(board, text)
        assert (decoded.from_sq, decoded.to_sq) == (mv.from_sq, mv.to_sq), (
            f"{text} decoded to {decoded.to_uci()} instead of {mv.to_uci()}"
        )


@pytest.mark.parametrize("fen", ROUND_TRIP_POSITIONS)
def test_notation_is_unique_across_legal_moves(fen):
    board = Board.from_fen(fen)
    names = [move_to_chinese(board, mv) for mv in legal_moves(board, board.side_to_move)]
    duplicates = {x for x in names if names.count(x) > 1}
    assert not duplicates, f"ambiguous notation produced: {duplicates}"


# --------------------------------------------------------------------------
# Sequences.
# --------------------------------------------------------------------------

def test_moves_to_chinese_replays_a_sequence():
    board = Board.from_fen()
    seq = ["h2e2", "h9g7", "h0g2", "i9h9"]
    assert moves_to_chinese(board, seq) == ["炮二平五", "马８进７", "马二进三", "车９平８"]
    # The caller's board must not be mutated.
    assert board.to_fen() == Board.from_fen().to_fen()


def test_moves_to_chinese_stops_on_desync_instead_of_raising():
    board = Board.from_fen()
    # Second move has no piece on its origin square.
    assert moves_to_chinese(board, ["h2e2", "e4e5"]) == ["炮二平五"]


def test_every_opening_book_line_is_legal_and_renders():
    """Guards against a mislabelled or illegal book entry silently shipping."""
    from app.xiangqi.rules import find_legal_move

    for line in OPENING_BOOK:
        board = Board.from_fen()
        for uci in line.moves:
            mv = Move.from_uci(uci)
            assert find_legal_move(board, mv) is not None, f"{line.name}: {uci} is illegal"
            assert move_to_chinese(board, mv)
            board.apply_move(mv)


def test_opening_book_has_no_duplicate_move_sequences():
    seqs = [tuple(line.moves) for line in OPENING_BOOK]
    duplicates = {s for s in seqs if seqs.count(s) > 1}
    assert not duplicates, f"unreachable duplicate book lines: {duplicates}"
