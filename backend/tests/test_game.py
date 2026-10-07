import json

import pytest

from app.api.schemas import MoveResultResponse
from app.engine.ucci import PvLine
from app.game import GameSession, IllegalMoveError
from app.library.records import GameRecord, RecordError
from app.library.store import GameStore, StoreError
from tests.test_library import VALID  # the canonical replay-file fixture


class FakeEngine:
    """Minimal engine stub so game-state/history logic can be tested without
    spawning the real Pikafish binary."""

    def is_running(self) -> bool:
        return True

    def new_game(self) -> None:
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3) -> list[PvLine]:
        return [PvLine(multipv=1, score_cp=0, score_mate=None, pv=[])]


@pytest.fixture
def session() -> GameSession:
    s = GameSession(FakeEngine())
    s.new_game()
    return s


def test_undo_reverts_board_and_history(session: GameSession):
    r1 = session.make_move("c3", "c4")
    r2 = session.make_move("c6", "c5")
    assert session.move_history == ["c3c4", "c6c5"]

    result = session.undo()
    assert result["move_history"] == ["c3c4"]
    assert result["future_moves"] == ["c6c5"]
    assert result["fen"] == r1["fen"]
    assert result["fen"] != r2["fen"]


def test_redo_restores_undone_move(session: GameSession):
    session.make_move("c3", "c4")
    r2 = session.make_move("c6", "c5")
    session.undo()

    result = session.redo()
    assert result["move_history"] == ["c3c4", "c6c5"]
    assert result["future_moves"] == []
    assert result["fen"] == r2["fen"]


def test_undo_with_empty_history_raises(session: GameSession):
    with pytest.raises(IllegalMoveError):
        session.undo()


def test_redo_with_empty_redo_stack_raises(session: GameSession):
    session.make_move("c3", "c4")
    with pytest.raises(IllegalMoveError):
        session.redo()


def test_playing_new_move_after_undo_discards_old_future(session: GameSession):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.undo()  # move_history=["c3c4"], redo_stack=["c6c5"]

    result = session.make_move("h9", "g7")  # a different, genuinely new black move
    assert result["move_uci"] == "h9g7"
    assert session.move_history == ["c3c4", "h9g7"]

    payload = session.position_payload()
    assert payload["future_moves"] == []


def test_goto_navigates_to_arbitrary_ply(session: GameSession):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.make_move("h2", "e2")

    result = session.goto(1)
    assert result["move_history"] == ["c3c4"]
    assert result["future_moves"] == ["c6c5", "h2e2"]

    result = session.goto(3)
    assert result["move_history"] == ["c3c4", "c6c5", "h2e2"]
    assert result["future_moves"] == []

    result = session.goto(0)
    assert result["move_history"] == []
    assert result["future_moves"] == ["c3c4", "c6c5", "h2e2"]


def test_goto_out_of_range_raises(session: GameSession):
    session.make_move("c3", "c4")
    with pytest.raises(IllegalMoveError):
        session.goto(5)
    with pytest.raises(IllegalMoveError):
        session.goto(-1)


# --------------------------------------------------------------------------
# Multi-ply 悔棋/重做. A single undo in an engine game lands on the engine's
# turn, which the frontend would simply have replayed — so stepping back two
# plies to the player's own turn has to work.
# --------------------------------------------------------------------------

def test_undo_multiple_plies(session: GameSession):
    r1 = session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.make_move("h2", "e2")

    result = session.undo(2)
    assert result["move_history"] == ["c3c4"]
    assert result["fen"] == r1["fen"]
    assert result["future_moves"] == ["c6c5", "h2e2"]


def test_redo_multiple_plies(session: GameSession):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    r3 = session.make_move("h2", "e2")
    session.undo(2)

    result = session.redo(2)
    assert result["move_history"] == ["c3c4", "c6c5", "h2e2"]
    assert result["fen"] == r3["fen"]
    assert result["future_moves"] == []


def test_undo_more_plies_than_played_raises(session: GameSession):
    session.make_move("c3", "c4")
    with pytest.raises(IllegalMoveError):
        session.undo(2)
    # ...and the session is untouched by the failed attempt.
    assert session.move_history == ["c3c4"]


def test_undo_zero_or_negative_plies_raises(session: GameSession):
    session.make_move("c3", "c4")
    with pytest.raises(IllegalMoveError):
        session.undo(0)


def test_move_history_chinese_tracks_move_history(session: GameSession):
    session.make_move("h2", "e2")
    session.make_move("h9", "g7")
    payload = session.position_payload()
    assert payload["move_history_chinese"] == ["炮二平五", "马８进７"]


# --------------------------------------------------------------------------
# Terminal positions. A move that ends the game must never be scored as a
# blunder: the post-move search returns no lines, which used to be read as
# eval 0 and produced a ~99999cp "loss" on a winning move.
# --------------------------------------------------------------------------

class MateScoringEngine:
    """Reports a mate-in-1 for the side to move, preferring one specific move,
    so we can play a DIFFERENT mating move and check how it is scored."""

    def __init__(self, best_move: str):
        self.best_move = best_move

    def is_running(self) -> bool:
        return True

    def new_game(self) -> None:
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3):
        return [PvLine(multipv=1, score_cp=None, score_mate=1, pv=[self.best_move])]


# Black general alone on e9; red chariot on a8 seals rank 1 while either of the
# chariots on b7/i7 can drop to the back rank for mate.
TWO_MATES_FEN = "4k4/R8/1R6R/9/9/9/9/9/9/3K5 w - - 0 1"


def test_delivering_mate_is_best_even_when_the_engine_preferred_another_mate():
    session = GameSession(MateScoringEngine(best_move="b7b9"))
    session.new_game(TWO_MATES_FEN)

    result = session.make_move("i7", "i9")  # a different, equally valid mate

    assert result["game_status"] == "checkmate"
    assert result["winner"] == "w"
    assert result["cp_loss"] == 0
    assert result["label"] == "最佳"
    assert "绝杀" in result["explanation"]


def test_mate_sets_a_decisive_eval_for_the_winning_side():
    session = GameSession(MateScoringEngine(best_move="b7b9"))
    session.new_game(TWO_MATES_FEN)
    result = session.make_move("i7", "i9")
    assert result["eval_cp"] is not None and result["eval_cp"] > 50_000


def test_engine_is_not_queried_once_the_game_is_over():
    session = GameSession(MateScoringEngine(best_move="b7b9"))
    session.new_game(TWO_MATES_FEN)
    session.make_move("i7", "i9")
    assert session.current_lines() == []


# --------------------------------------------------------------------------
# The wire contract: the move result must carry the intent rows plus a
# follow-up PV, and it must validate against the response model the API uses.
# --------------------------------------------------------------------------

class PvEngine:
    """Returns a fixed PV so follow-up rendering can be tested without the
    real engine."""

    def __init__(self, pv: list[str]):
        self.pv = pv

    def is_running(self) -> bool:
        return True

    def new_game(self) -> None:
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3) -> list[PvLine]:
        return [PvLine(multipv=1, score_cp=30, score_mate=None, pv=list(self.pv))]


def test_move_result_carries_intents_and_validates_against_schema(session: GameSession):
    result = session.make_move("h2", "e2")
    assert result["intents"], "炮二平五 should at least get a goal row"
    assert result["intent_text"] in result["explanation"]
    MoveResultResponse.model_validate(result)


def test_follow_up_shows_the_expected_continuation_in_chinese():
    session = GameSession(PvEngine(["h9g7", "h0g2", "b9c7", "c3c4", "c6c5"]))
    session.new_game()
    result = session.make_move("h2", "e2")
    assert result["follow_up"] == {
        "moves_uci": ["h9g7", "h0g2", "b9c7", "c3c4"],
        "moves_chinese": ["马８进７", "马二进三", "马２进３", "兵七进一"],
    }
    MoveResultResponse.model_validate(result)  # the non-null FollowUpOut shape


def test_follow_up_pads_unrenderable_moves_with_null():
    session = GameSession(PvEngine(["h9g7", "a1a2"]))  # a1 is empty after 炮二平五
    session.new_game()
    result = session.make_move("h2", "e2")
    assert result["follow_up"] == {
        "moves_uci": ["h9g7", "a1a2"],
        "moves_chinese": ["马８进７", None],
    }


def test_follow_up_is_none_without_engine_lines(session: GameSession):
    result = session.make_move("h2", "e2")
    assert result["follow_up"] is None


def test_follow_up_and_intents_are_empty_when_the_game_ends():
    session = GameSession(MateScoringEngine(best_move="b7b9"))
    session.new_game(TWO_MATES_FEN)
    result = session.make_move("i7", "i9")
    assert result["follow_up"] is None
    assert result["intents"] == []
    assert result["intent_text"] is None


def test_follow_up_is_none_when_the_game_ends_by_repetition():
    session = GameSession(PvEngine(["a4a5"]))
    session.new_game("4k4/9/9/9/9/R8/9/9/5K3/9 w - - 0 1")
    for from_sq, to_sq in [("a4", "a5"), ("e9", "d9"), ("a5", "a4"), ("d9", "e9"),
                           ("a4", "a5"), ("e9", "d9"), ("a5", "a4"), ("d9", "e9")]:
        result = session.make_move(from_sq, to_sq)
    assert result["game_status"] == "draw_repetition"   # the position repeats a third time
    assert result["follow_up"] is None
    assert result["intents"] == []
    assert result["intent_text"] is None


# --------------------------------------------------------------------------
# 对方停一手（空着假想）: the engine's line for the mover if the opponent
# kept passing — chained side-flipped ("null move") positions, up to ten own
# moves. Pikafish exits on the illegal position where the checked side does
# not move, so the chain stops just after a move that gives check.
# --------------------------------------------------------------------------

class PassingChainEngine:
    """Answers each opponent-passes probe (analyze without `moves`) with the
    next queued move and records every probed FEN."""

    def __init__(self, passing_moves: list[str]):
        self.passing_moves = list(passing_moves)
        self.probes: list[str] = []

    def is_running(self) -> bool:
        return True

    def new_game(self) -> None:
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3) -> list[PvLine]:
        if moves is None:  # an opponent-passes probe
            self.probes.append(fen)
            uci = self.passing_moves.pop(0) if self.passing_moves else None
            return [PvLine(multipv=1, score_cp=0, score_mate=None, pv=[uci] if uci else [])]
        return [PvLine(multipv=1, score_cp=0, score_mate=None, pv=[])]


def test_passing_plan_shows_a_single_move_when_the_probe_yields_one():
    session = GameSession(PassingChainEngine(["e2e6"]))
    session.new_game()
    result = session.make_move("h2", "e2")  # 炮二平五
    assert result["passing_plan"] == {"moves_uci": ["e2e6"], "moves_chinese": ["炮五进四"]}


def test_passing_plan_chains_ten_own_moves_when_the_opponent_keeps_passing():
    engine = PassingChainEngine(
        ["e2e6", "b2e2", "b0c2", "a0b0", "b0b1", "b1b2", "b2b3", "b3b4", "b4b5", "b5b6"]
    )
    session = GameSession(engine)
    session.new_game()
    result = session.make_move("h2", "e2")  # 炮二平五
    assert result["passing_plan"] == {
        "moves_uci": ["e2e6", "b2e2", "b0c2", "a0b0", "b0b1", "b1b2", "b2b3", "b3b4", "b4b5", "b5b6"],
        "moves_chinese": [
            "炮五进四", "炮八平五", "马八进七", "车九平八", "车八进一",
            "车八进一", "车八进一", "车八进一", "车八进一", "车八进一",
        ],
    }
    assert len(engine.probes) == 10  # one side-flipped probe per own move
    for probed in engine.probes:
        assert probed.split()[1] == "w"  # it is always the mover's turn again
    assert engine.probes[0].split()[0] == result["fen"].split()[0]
    MoveResultResponse.model_validate(result)  # the non-null PassingPlanOut shape


def test_passing_plan_stops_after_ten_moves():
    engine = PassingChainEngine(
        ["e2e6", "b2e2", "b0c2", "a0b0", "b0b1", "b1b2", "b2b3", "b3b4", "b4b5", "b5b6", "b6b7"]
    )
    session = GameSession(engine)
    session.new_game()
    result = session.make_move("h2", "e2")
    assert len(result["passing_plan"]["moves_uci"]) == 10
    assert len(engine.probes) == 10  # the eleventh queued move is never probed


def test_passing_plan_ends_with_the_move_that_gives_check():
    # Passing out of check is not a legal hypothetical: the chain keeps the
    # checking move and stops. The third queued move is never probed.
    engine = PassingChainEngine(["a2a3", "a3e3", "b0b1"])
    session = GameSession(engine)
    session.new_game("4k4/9/9/9/9/9/9/9/R8/3K5 w - - 0 1")
    result = session.make_move("a1", "a2")  # quiet setup
    assert result["passing_plan"] == {
        "moves_uci": ["a2a3", "a3e3"],
        "moves_chinese": ["车九进一", "车九平五"],
    }
    assert len(engine.probes) == 2


def test_no_passing_plan_probe_when_the_move_gives_check():
    # A side-flipped position where the checked side does not move made the
    # real engine exit; the probe must be skipped entirely.
    engine = PassingChainEngine(["e2e6"])
    session = GameSession(engine)
    session.new_game("4k4/9/9/9/7R1/9/9/9/r8/R2K5 w - - 0 1")
    result = session.make_move("h5", "h9")  # 车二进四, checks along rank 0
    assert result["passing_plan"] is None
    assert engine.probes == []


def test_passing_plan_is_none_when_the_game_ends():
    session = GameSession(MateScoringEngine(best_move="b7b9"))
    session.new_game(TWO_MATES_FEN)
    result = session.make_move("i7", "i9")
    assert result["passing_plan"] is None


def test_passing_plan_is_none_without_engine_lines(session: GameSession):
    result = session.make_move("h2", "e2")
    assert result["passing_plan"] is None


# --------------------------------------------------------------------------
# The same opponent-passes chain for the ENGINE'S preferred move (the
# 更好的选择 block): "if you played the best move and the opponent kept
# passing, what would you do next".
# --------------------------------------------------------------------------

class BestPlanEngine:
    """Returns a fixed best move for real searches (the second real search
    scores worse, so a different played move is judged a loss) and serves the
    queued moves to the opponent-passes probes: the played move's chain first,
    then the best move's."""

    def __init__(self, best_move: str, passing_moves: list[str], after_score: int = 60):
        self.best_move = best_move
        self.passing_moves = list(passing_moves)
        self.after_score = after_score
        self.probes: list[str] = []
        self.real_calls = 0

    def is_running(self) -> bool:
        return True

    def new_game(self) -> None:
        pass

    def analyze(self, fen, moves=None, depth=14, movetime_ms=None, multipv=3) -> list[PvLine]:
        if moves is None:  # an opponent-passes probe
            self.probes.append(fen)
            uci = self.passing_moves.pop(0) if self.passing_moves else None
            return [PvLine(multipv=1, score_cp=0, score_mate=None, pv=[uci] if uci else [])]
        self.real_calls += 1
        score = 0 if self.real_calls == 1 else self.after_score
        return [PvLine(multipv=1, score_cp=score, score_mate=None, pv=[self.best_move])]


def test_best_passing_plan_shows_the_engine_picks_own_chain():
    # "e5e5" targets an empty square: it ends the played move's chain so the
    # remaining queued moves go to the best move's chain.
    engine = BestPlanEngine("c3c4", ["e2e6", "e5e5", "b0c2", "a0b0"])
    session = GameSession(engine)
    session.new_game()
    result = session.make_move("h2", "e2")  # 炮二平五, worse than the engine's 兵七进一
    assert result["passing_plan"] == {
        "moves_uci": ["e2e6"],
        "moves_chinese": ["炮五进四"],
    }
    assert result["best_passing_plan"] == {
        "moves_uci": ["b0c2", "a0b0"],
        "moves_chinese": ["马八进七", "车九平八"],
    }
    # played chain: the move, the terminator; best chain: two moves, then the
    # empty probe that ends it.
    assert len(engine.probes) == 5
    MoveResultResponse.model_validate(result)  # the non-null shape


def test_no_best_passing_plan_when_the_played_move_matches_the_engine():
    engine = BestPlanEngine("c3c4", ["b0c2"])
    session = GameSession(engine)
    session.new_game()
    result = session.make_move("c3", "c4")
    assert result["best_passing_plan"] is None
    assert len(engine.probes) == 2  # the played chain only: one move, then the empty probe


def test_no_best_passing_plan_when_the_played_move_is_not_worse():
    engine = BestPlanEngine("c3c4", ["b0c2"], after_score=0)  # same evaluation
    session = GameSession(engine)
    session.new_game()
    result = session.make_move("h2", "e2")
    assert result["best_passing_plan"] is None
    assert len(engine.probes) == 2  # the played chain only: one move, then the empty probe


def test_no_best_passing_plan_when_the_best_move_gives_check():
    engine = BestPlanEngine("h5h9", ["a1a2"])
    session = GameSession(engine)
    session.new_game("4k4/9/9/9/7R1/9/9/9/r8/R2K5 w - - 0 1")
    result = session.make_move("a0", "a1")  # captures the rook; worse than the check
    assert result["best_passing_plan"] is None
    assert result["passing_plan"] is not None  # the played move's own chain ran
    # Both probes belong to the played chain (one move, then the empty probe):
    # the best move's chain was never probed.
    assert len(engine.probes) == 2


# --------------------------------------------------------------------------
# Notes: per-ply notes ride along with their move through 悔棋/重做 and die with
# an abandoned branch, alongside one whole-game note.
# --------------------------------------------------------------------------

def test_note_rides_along_with_undo_and_redo(session):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.set_note(2, "黑方这步不好")
    session.undo()
    assert session.line_notes() == ["", "黑方这步不好"]
    session.redo()
    assert session.line_notes() == ["", "黑方这步不好"]
    assert session.move_notes == ["", "黑方这步不好"]


def test_a_new_move_drops_the_abandoned_branch_note(session):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.set_note(2, "不要这步")
    session.undo()
    session.make_move("h9", "g7")
    assert session.line_notes() == ["", ""]
    assert session.move_notes == ["", ""]


def test_set_note_addresses_a_ply_in_the_redo_branch(session):
    # Review Focus 5: a note may be written for a ply that is currently undone.
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.undo()
    session.set_note(2, "先记下，之后再说")
    assert session.move_notes == [""]                    # nothing leaks into the applied line
    assert session.redo_notes == ["先记下，之后再说"]
    assert session.line_notes() == ["", "先记下，之后再说"]
    assert session.redo()["notes"] == ["", "先记下，之后再说"]


def test_set_note_addresses_a_two_ply_redo_branch(session):
    # With one undone ply `len(redo_stack) - k` and a naive `k - 1` coincide;
    # with two they disagree, and the naive index puts the note on the wrong
    # ply (or silently loses it) once the branch is redone.
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.make_move("h2", "e2")
    session.undo(2)  # redo_stack == ["h2e2", "c6c5"]
    session.set_note(1, "第一步")
    session.set_note(2, "第二步")  # redo_stack[1] — NOT the LIFO's first slot
    session.set_note(3, "第三步")  # redo_stack[0]
    assert session.line_notes() == ["第一步", "第二步", "第三步"]

    session.redo(2)
    assert session.move_notes == ["第一步", "第二步", "第三步"]


def test_set_note_rejects_an_out_of_range_ply(session):
    session.make_move("c3", "c4")
    for bad in (0, 2):
        with pytest.raises(IllegalMoveError):
            session.set_note(bad, "x")


def test_notes_payload_covers_the_whole_line(session):
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.undo()
    payload = session.position_payload()
    assert payload["notes"] == ["", ""]
    assert len(payload["notes"]) == len(payload["move_history"]) + len(payload["future_moves"])


def test_whole_game_note_is_separate_from_ply_notes(session):
    session.make_move("c3", "c4")
    session.set_note(None, "整局：开局太软")
    assert session.game_note == "整局：开局太软"
    assert session.move_notes == [""]


# --------------------------------------------------------------------------
# Record lifecycle: the session auto-saves the applied line to the game store,
# lazily creating the record on the first move and rewriting it on every
# mutation. store=None keeps a session purely in memory (the whole suite above
# depends on that), and a failed write must never lose a move.
# --------------------------------------------------------------------------

@pytest.fixture
def stored(tmp_path):
    """A session with a real store on disk, plus the store itself."""
    store = GameStore(tmp_path)
    session = GameSession(FakeEngine(), store)
    session.new_game()
    return session, store


def test_first_move_creates_the_record_lazily(stored):
    session, store = stored
    assert session.record_id is None
    result = session.make_move("c3", "c4")
    assert result["game_id"] == session.record_id is not None
    assert result["save_error"] is None
    assert len(store.list()) == 1
    assert store.load(session.record_id).moves == ["c3c4"]


def test_undo_rewrites_the_saved_line(stored):
    session, store = stored
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.set_note(2, "黑方这步不好")
    session.undo()
    record = store.load(session.record_id)
    assert record.moves == ["c3c4"]
    assert record.notes == [""]   # Review Focus 5: the undone ply is not in the file


def test_undoing_to_the_start_truncates_the_saved_line(stored):
    session, store = stored
    session.make_move("c3", "c4")
    session.make_move("c6", "c5")
    session.undo(2)
    record = store.load(session.record_id)      # the record survives
    assert record.moves == []
    assert record.notes == []


def test_a_failed_save_is_reported_without_losing_the_move(tmp_path):
    # Review Focus 4
    class BrokenStore(GameStore):
        def save(self, record):
            raise StoreError("保存对局失败：磁盘只读")

    session = GameSession(FakeEngine(), BrokenStore(tmp_path))
    session.new_game()
    result = session.make_move("c3", "c4")
    assert result["save_error"] == "保存对局失败：磁盘只读"
    assert session.move_history == ["c3c4"]      # the move still stands
    assert session.undo()["move_history"] == []  # and history still works


def test_import_rejects_a_record_whose_notes_do_not_match_its_moves(tmp_path):
    # Review Focus 2: the API hands the session a pydantic model that was never
    # run through GameRecord.parse, so import_record re-validates.
    session = GameSession(FakeEngine(), GameStore(tmp_path))
    session.new_game()
    with pytest.raises(RecordError):
        session.import_record(GameRecord(**{**VALID, "notes": ["只有一条"]}))


def test_open_record_does_not_bump_updated_at(stored):
    session, store = stored
    session.make_move("c3", "c4")
    before = store.load(session.record_id).updated_at
    session.open_record(session.record_id)
    assert store.load(session.record_id).updated_at == before


def test_open_record_replays_the_same_notation(stored):
    # The guard for coordinate/start-fen mistakes: move_to_chinese needs the
    # board BEFORE the move, so a wrong replay shows up as different text.
    session, store = stored
    for frm, to in [("c3", "c4"), ("c6", "c5"), ("b2", "e2")]:
        session.make_move(frm, to)
    expected = list(session.position_payload()["move_history_chinese"])

    reopened = GameSession(FakeEngine(), store)
    reopened.open_record(session.record_id)
    assert reopened.position_payload()["move_history_chinese"] == expected
    assert reopened.record_id == session.record_id
    assert reopened.saved_at == session.saved_at


def test_open_record_adopts_the_id_it_loaded_by(stored):
    # A hand-renamed file (xyz.json holding "id": "abc") used to leave the
    # session on the in-file id, so the next move wrote abc.json and orphaned
    # the file the player had opened, duplicating the library entry.
    session, store = stored
    (store.directory / "xyz.json").write_text(
        json.dumps({**VALID, "id": "abc"}), encoding="utf-8"
    )
    session.open_record("xyz")
    assert session.record_id == "xyz"

    session.make_move("c3", "c4")  # 兵七进一 — red to move after h2e2/h9g7
    saved = store.load("xyz")
    assert saved.id == "xyz"  # the in-file id is normalised on the next save
    assert saved.moves == ["h2e2", "h9g7", "c3c4"]
    assert not (store.directory / "abc.json").exists()


def test_line_plies_matches_the_live_move_results(stored):
    # Ties the loaded-game board rendering to reality: the per-ply FENs a
    # library game renders from must equal the ones the live game produced.
    session, _ = stored
    results = [session.make_move("c3", "c4"), session.make_move("c6", "c5")]
    plies = session._line_plies()
    assert [p["fen"] for p in plies] == [r["fen"] for r in results]
    assert [p["move_uci"] for p in plies] == [r["move_uci"] for r in results]
    assert [p["move_chinese"] for p in plies] == [r["move_chinese"] for r in results]
    assert [p["side_to_move"] for p in plies] == [r["side_to_move"] for r in results]


def test_open_record_with_an_illegal_move_leaves_the_session_untouched(stored):
    # Review Focus 3; a0b1 is a diagonal 車 move, so it can never be legal.
    session, store = stored
    session.make_move("c3", "c4")
    broken = GameRecord(**{
        **VALID, "id": "20260101-0000-dead",
        "moves": ["c3c4", "c6c5", "a0b1"], "notes": ["", "", ""],
    })
    store.save(broken)  # save() is a dumb writer — it does not run parse
    with pytest.raises(RecordError):
        session.open_record(broken.id)
    assert session.move_history == ["c3c4"]
    assert session.record_id != broken.id


def test_open_record_rejects_a_move_that_does_not_round_trip(stored):
    # Move.from_uci silently truncates "c3c4x" to c3c4, which would otherwise
    # be replayed as a legal move while the bogus string stayed in
    # move_history and reached the engine as a `position ... moves` token.
    session, store = stored
    session.make_move("c3", "c4")
    broken = GameRecord(**{
        **VALID, "id": "20260101-0000-beef",
        "moves": ["c3c4x"], "notes": [""],
    })
    store.save(broken)
    with pytest.raises(RecordError):
        session.open_record(broken.id)
    assert session.move_history == ["c3c4"]


def test_save_as_copies_the_line_and_switches_identity(stored):
    session, store = stored
    session.make_move("c3", "c4")
    original = session.record_id
    session.save_as("我的研究")
    assert session.record_name == "我的研究"
    assert session.record_id != original
    assert store.load(original).name != "我的研究"
    assert store.load(session.record_id).moves == ["c3c4"]


def test_import_keeps_the_files_id_when_free_and_mints_one_when_taken(stored):
    session, store = stored
    record = GameRecord.parse(VALID)   # h2e2 / h9g7 — legal from the start position
    session.import_record(record)
    assert session.record_id == record.id
    session.import_record(record)      # the same id again
    assert session.record_id != record.id
    assert len(store.list()) == 2


def test_a_failed_import_leaves_the_session_unchanged(tmp_path):
    # The import used to replay into the session BEFORE storing, so a failed
    # write left the backend on the imported line while the frontend still
    # showed — and played moves against — the previous game.
    class BrokenStore(GameStore):
        def save(self, record):
            raise StoreError("保存对局失败：磁盘只读")

    session = GameSession(FakeEngine(), BrokenStore(tmp_path))
    session.new_game()
    session.make_move("c3", "c4")
    session.set_note(1, "原来的笔记")
    session.set_note(None, "整局笔记")
    fen_before = session.board.to_fen()
    record_id = session.record_id
    assert record_id is not None  # the first move created the (unsaved) record

    with pytest.raises(StoreError):
        session.import_record(GameRecord.parse(VALID))

    assert session.move_history == ["c3c4"]
    assert session.record_id == record_id
    assert session.line_notes() == ["原来的笔记"]
    assert session.game_note == "整局笔记"
    assert session.board.to_fen() == fen_before


def test_import_mints_a_new_id_when_the_files_id_is_unusable(tmp_path):
    session = GameSession(FakeEngine(), GameStore(tmp_path))
    session.new_game()
    session.import_record(GameRecord.parse({**VALID, "id": "我的对局"}))
    assert session.record_id != "我的对局"
    assert session.move_history == ["h2e2", "h9g7"]
    assert len(GameStore(tmp_path).list()) == 1


def test_new_game_releases_the_record_identity(stored):
    session, store = stored
    session.make_move("c3", "c4")
    first_id = session.record_id
    first_updated = store.load(first_id).updated_at

    session.new_game()
    assert session.record_id is None
    session.make_move("h2", "e2")

    assert session.record_id is not None
    assert session.record_id != first_id
    # The released game's file is untouched: its next move would have landed
    # there if 新对局 had kept the identity.
    assert store.load(first_id).moves == ["c3c4"]
    assert store.load(first_id).updated_at == first_updated
    assert len(store.list()) == 2


def test_a_session_without_a_store_stays_pure(session):
    result = session.make_move("c3", "c4")
    assert result["game_id"] is None
    assert result["save_error"] is None
