"""重复局面判定 tests — Chinese rules, where perpetual check loses."""
from app.engine.ucci import PvLine
from app.game import GameSession
from app.xiangqi.board import BLACK, RED
from app.xiangqi.repetition import evaluate_repetition, repetition_warning


class FakeEngine:
    def is_running(self):
        return True

    def new_game(self):
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3):
        return [PvLine(multipv=1, score_cp=0, score_mate=None, pv=[])]


# --------------------------------------------------------------------------
# The pure verdict function.
# --------------------------------------------------------------------------

def test_no_verdict_before_the_third_occurrence():
    keys = ["A", "B", "A"]
    assert evaluate_repetition(keys, [RED, BLACK], [False, False]) is None


def test_plain_repetition_is_a_draw():
    keys = ["A", "B", "A", "B", "A"]
    verdict = evaluate_repetition(keys, [RED, BLACK, RED, BLACK], [False] * 4)
    assert verdict is not None
    assert verdict.status == "draw_repetition"
    assert verdict.winner is None


def test_perpetual_check_loses_for_the_checking_side():
    keys = ["A", "B", "A", "B", "A"]
    # Red checks on every one of its moves; black never does.
    verdict = evaluate_repetition(
        keys, [RED, BLACK, RED, BLACK], [True, False, True, False]
    )
    assert verdict is not None
    assert verdict.status == "perpetual_loss"
    assert verdict.perpetual_side == RED
    assert verdict.winner == BLACK
    assert "长将" in verdict.note


def test_mutual_perpetual_check_is_a_draw():
    keys = ["A", "B", "A", "B", "A"]
    verdict = evaluate_repetition(keys, [RED, BLACK, RED, BLACK], [True] * 4)
    assert verdict is not None
    assert verdict.status == "draw_repetition"
    assert verdict.winner is None


def test_intermittent_checks_are_not_perpetual():
    keys = ["A", "B", "A", "B", "A"]
    # Red checked only once, so it is not forcing the repetition.
    verdict = evaluate_repetition(
        keys, [RED, BLACK, RED, BLACK], [True, False, False, False]
    )
    assert verdict is not None
    assert verdict.status == "draw_repetition"


def test_warning_fires_on_the_second_occurrence():
    keys = ["A", "B", "A"]
    warning = repetition_warning(keys, [RED, BLACK], [True, False])
    assert warning is not None
    assert "长将" in warning
    # ...and stops once the verdict itself is due.
    assert repetition_warning(["A", "B", "A", "B", "A"], [RED, BLACK] * 2, [True, False] * 2) is None


# --------------------------------------------------------------------------
# End-to-end through a real game session.
# --------------------------------------------------------------------------

# Red chariot on a8 shuffles between rows 0 and 1 checking the lone black
# general, which shuffles between e9 and e8 to escape. Red checks every time.
PERPETUAL_FEN = "4k4/R8/9/9/9/9/9/9/9/3K5 w - - 0 1"
PERPETUAL_CYCLE = [("a8", "a9"), ("e9", "e8"), ("a9", "a8"), ("e8", "e9")]


def test_perpetual_check_is_judged_a_loss_in_a_real_game():
    session = GameSession(FakeEngine())
    session.new_game(PERPETUAL_FEN)

    result = None
    for _ in range(2):
        for frm, to in PERPETUAL_CYCLE:
            result = session.make_move(frm, to)

    assert result["game_status"] == "perpetual_loss"
    assert result["winner"] == BLACK, "red forced the repetition with checks, so red loses"
    assert "长将" in result["result_note"]


def test_repetition_bookkeeping_unwinds_on_undo():
    session = GameSession(FakeEngine())
    session.new_game(PERPETUAL_FEN)
    for frm, to in PERPETUAL_CYCLE:
        session.make_move(frm, to)

    assert len(session.position_keys) == 5  # start + 4 plies
    session.undo(2)
    assert len(session.position_keys) == 3
    assert len(session.move_sides) == 2
    assert len(session.move_gave_check) == 2

    session.redo(2)
    assert len(session.position_keys) == 5
    assert len(session.move_gave_check) == 4


def test_checks_are_recorded_for_the_right_side():
    session = GameSession(FakeEngine())
    session.new_game(PERPETUAL_FEN)
    session.make_move("a8", "a9")   # red checks
    session.make_move("e9", "e8")   # black escapes, no check
    assert session.move_sides == [RED, BLACK]
    assert session.move_gave_check == [True, False]
