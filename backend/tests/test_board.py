from app.xiangqi.board import Board, Move, START_FEN, RED
from app.xiangqi.movegen import legal_moves


def test_start_fen_roundtrip():
    board = Board.from_fen(START_FEN)
    assert board.to_fen() == START_FEN


def test_start_position_legal_move_count():
    board = Board.from_fen(START_FEN)
    moves = legal_moves(board, RED)
    assert len(moves) == 44


def test_apply_and_undo_move():
    board = Board.from_fen(START_FEN)
    fen_before = board.to_fen()
    mv = Move.from_uci("h2e2")
    board.apply_move(mv)
    assert board.to_fen() != fen_before
    board.undo_move()
    assert board.to_fen() == fen_before


def test_move_uci_roundtrip():
    mv = Move.from_uci("h2e2")
    assert mv.to_uci() == "h2e2"
    mv2 = Move.from_uci("a0a1")
    assert mv2.to_uci() == "a0a1"
