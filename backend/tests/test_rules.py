from app.xiangqi.board import Board, Move, RED, BLACK
from app.xiangqi.movegen import is_in_check, is_checkmate, legal_moves
from app.xiangqi.rules import game_status


def test_checkmate_two_chariots():
    fen = "R3k4/9/9/9/9/4R4/9/9/9/3K5 b - - 0 1"
    board = Board.from_fen(fen)
    assert is_in_check(board, BLACK)
    assert is_checkmate(board, BLACK)
    assert legal_moves(board, BLACK) == []
    status = game_status(board)
    assert status["status"] == "checkmate"
    assert status["winner"] == RED


def test_check_but_not_checkmate_with_escape():
    # Same as above but the row-0 chariot is moved off row 0, leaving d0 as an
    # escape square for the black general.
    fen = "9/R8/9/9/9/4R4/9/9/9/3K5 b - - 0 1"
    board = Board.from_fen(fen)
    # place black general at e0 manually since row0 must stay empty of the chariot
    board.grid[0][4] = "k"
    assert is_in_check(board, BLACK)
    assert not is_checkmate(board, BLACK)


def test_flying_general_rule_blocks_exposing_moves():
    fen = "4k4/9/9/9/9/4R4/9/9/9/4K4 w - - 0 1"
    board = Board.from_fen(fen)
    moves = legal_moves(board, RED)
    move_pairs = {(m.from_sq, m.to_sq) for m in moves}
    # Sliding the chariot off the e-file would expose the generals to each other.
    assert ((5, 4), (5, 0)) not in move_pairs
    # Sliding it up/down the e-file still blocks the generals; that's legal.
    assert ((5, 4), (4, 4)) in move_pairs


def test_generals_facing_detection():
    board = Board()
    board.grid[0][4] = "k"
    board.grid[9][4] = "K"
    assert board.generals_facing()
    board.grid[5][4] = "R"
    assert not board.generals_facing()
