from app.xiangqi.board import Board, Move, RED, BLACK
from app.xiangqi.rules import find_legal_move
from app.analysis.tactics import (
    find_hanging_pieces,
    find_forks,
    find_cannon_threats,
    find_hollow_cannon,
    find_pinned_pieces,
    attackers_of,
    static_exchange_eval,
)


def test_hanging_chariot_undefended():
    fen = "4r4/5k3/9/9/9/4R4/9/9/3K5/9 w - - 0 1"
    board = Board.from_fen(fen)
    tags = find_hanging_pieces(board, RED)
    assert any(t.piece_sq == (5, 4) for t in tags)


def test_no_hanging_when_defended():
    # Red chariot at e5 attacked by black chariot at e0, but defended by a
    # second red chariot also on the e-file behind it.
    fen = "4r4/5k3/9/9/9/4R4/4R4/9/3K5/9 w - - 0 1"
    board = Board.from_fen(fen)
    tags = find_hanging_pieces(board, RED)
    assert not any(t.piece_sq == (5, 4) for t in tags)


def test_horse_fork():
    fen = "9/5k3/9/3a1b3/9/4N4/9/9/3K5/9 w - - 0 1"
    board = Board.from_fen(fen)
    tags = find_forks(board, RED)
    fork_tags = [t for t in tags if t.piece_sq == (5, 4)]
    assert len(fork_tags) == 1
    assert set(fork_tags[0].target_sqs) == {(3, 3), (3, 5)}


def test_cannon_threat():
    # Red cannon on e5, one black screen piece on e2, black chariot on e0:
    # cannon can jump the screen and capture the chariot next move.
    fen = "4r4/5k3/4a4/9/9/4C4/9/9/3K5/9 w - - 0 1"
    board = Board.from_fen(fen)
    tags = find_cannon_threats(board, RED)
    assert any(t.piece_sq == (5, 4) and (0, 4) in t.target_sqs for t in tags)


def test_hollow_cannon():
    fen = "4k4/9/9/9/9/4C4/9/9/3K5/9 w - - 0 1"
    board = Board.from_fen(fen)
    tags = find_hollow_cannon(board, RED)
    assert len(tags) == 0  # zero pieces between cannon and general -> not hollow-cannon yet
    fen2 = "4k4/4a4/9/9/9/4C4/9/9/3K5/9 w - - 0 1"
    board2 = Board.from_fen(fen2)
    tags2 = find_hollow_cannon(board2, RED)
    assert any(t.piece_sq == (5, 4) for t in tags2)


# --------------------------------------------------------------------------
# Static exchange evaluation. The old detector called any attacked+undefended
# piece "hanging", which fired on ordinary pawn tension every single move.
# --------------------------------------------------------------------------

def test_see_wins_an_undefended_chariot():
    board = Board.from_fen("3k5/9/9/9/9/9/9/9/r8/R3K4 w - - 0 1")
    assert static_exchange_eval(board, (9, 0), BLACK) == 9.0


def test_see_declines_a_losing_exchange():
    # Red chariot on a0 is backed up by a second chariot, so taking loses 9 for 9.
    board = Board.from_fen("3k5/9/9/9/9/9/9/R8/r8/R3K4 w - - 0 1")
    assert static_exchange_eval(board, (9, 0), BLACK) == 0.0


def test_see_sees_through_an_xray_attacker():
    # Black chariot in front, black cannon behind it on the same file.
    board = Board.from_fen("3k5/9/9/9/9/9/c8/9/r8/R3K4 w - - 0 1")
    assert static_exchange_eval(board, (9, 0), BLACK) == 9.0


def test_see_ignores_a_pinned_attacker():
    # Black chariot on e5 is pinned down the e-file by the red chariot on e1.
    # It attacks the red horse on g5, but capturing would step off the file and
    # expose its own general, so the horse is not really threatened.
    board = Board.from_fen("4k4/9/9/9/4r1N2/9/9/9/4R4/3K5 b - - 0 1")
    assert static_exchange_eval(board, (4, 6), BLACK) == 0.0
    # Stepping off the file is what is illegal; sliding along it stays legal.
    assert find_legal_move(board, Move.from_uci("e5g5")) is None
    assert find_legal_move(board, Move.from_uci("e5e6")) is not None


def test_ordinary_pawn_tension_is_not_reported_as_hanging():
    """兵七进一 / 卒７进１ leaves the pawns facing each other. That is normal
    opening play and must not produce a 「随时会被白吃」 warning."""
    board = Board.from_fen()
    for uci in ("c3c4", "c6c5"):
        board.apply_move(Move.from_uci(uci))
    assert find_hanging_pieces(board, RED) == []
    assert find_hanging_pieces(board, BLACK) == []


def test_starting_position_reports_no_tactics_at_all():
    board = Board.from_fen()
    assert find_hanging_pieces(board, RED) == []
    assert find_forks(board, RED) == []
    assert find_pinned_pieces(board, RED) == []


# --------------------------------------------------------------------------
# Pins: only genuine immobility, not "one of my moves is restricted".
# --------------------------------------------------------------------------

def test_genuinely_pinned_horse_is_reported():
    board = Board.from_fen("4k4/9/9/9/9/9/9/4r4/4N4/4K4 w - - 0 1")
    tags = find_pinned_pieces(board, RED)
    assert any(t.piece_sq == (8, 4) for t in tags)


def test_piece_that_can_still_move_is_not_pinned():
    board = Board.from_fen("3k5/9/9/9/9/9/9/9/4N4/4K4 w - - 0 1")
    assert find_pinned_pieces(board, RED) == []


def test_flying_general_constraint_is_labelled_separately():
    # The red horse on e1 sits between the two generals: it cannot move without
    # exposing them to each other, which is a different fault from a real pin.
    board = Board.from_fen("4k4/9/9/9/9/9/9/9/4N4/4K4 w - - 0 1")
    tags = find_pinned_pieces(board, RED)
    assert len(tags) == 1
    assert tags[0].detail["by_facing"] is True


# --------------------------------------------------------------------------
# Attacker enumeration.
# --------------------------------------------------------------------------

def test_attackers_of_finds_cannon_only_with_a_screen():
    without_screen = Board.from_fen("3k5/9/9/9/9/9/9/9/9/c3K4 w - - 0 1")
    assert attackers_of(without_screen, (9, 4), BLACK) == []
    with_screen = Board.from_fen("3k5/9/9/9/9/9/9/9/9/c1p1K4 w - - 0 1")
    assert (9, 0) in attackers_of(with_screen, (9, 4), BLACK)


def test_attackers_of_respects_a_blocked_horse_leg():
    free = Board.from_fen("3k5/9/9/9/9/9/9/9/2n6/4K4 w - - 0 1")
    assert (8, 2) in attackers_of(free, (9, 4), BLACK)
    # The leg of a horse going (+1,+2) is the square one step along the LONG
    # axis, i.e. (8,3) — not (9,3).
    blocked = Board.from_fen("3k5/9/9/9/9/9/9/9/2nP5/4K4 w - - 0 1")
    assert (8, 2) not in attackers_of(blocked, (9, 4), BLACK)
