import os

import pytest

from app.engine.ucci import UCCIEngine
from app.xiangqi.board import START_FEN

ENGINE_PATH = os.environ.get(
    "ENGINE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "engine", "pikafish"),
)

pytestmark = pytest.mark.skipif(
    not os.path.exists(ENGINE_PATH), reason="Pikafish binary not present; run scripts/setup_engine.sh"
)


def test_engine_handshake_and_multipv_analysis():
    engine = UCCIEngine(ENGINE_PATH)
    try:
        engine.start()
        assert engine.is_running()
        lines = engine.analyze(START_FEN, depth=8, multipv=3)
        assert len(lines) == 3
        assert lines[0].multipv == 1
        assert lines[0].best_move is not None
        # Starting position should be roughly balanced, not a huge swing.
        assert lines[0].score_cp is not None
        assert -300 < lines[0].score_cp < 300
    finally:
        engine.stop()


def test_engine_accepts_a_move_history():
    """The session sends `position fen <start> moves ...` rather than a bare
    current-position FEN, so the engine can see repetitions and apply 长将."""
    engine = UCCIEngine(ENGINE_PATH)
    try:
        engine.start()
        lines = engine.analyze(
            START_FEN, moves=["h2e2", "h9g7", "h0g2"], depth=8, multipv=2
        )
        assert lines and lines[0].best_move is not None
        # Black to move after three plies, so the reply must come from a black piece.
        assert lines[0].best_move[1] in "56789"
    finally:
        engine.stop()


def test_engine_reports_mate_scores():
    """Terminal handling depends on mate scores being parsed, not just cp."""
    engine = UCCIEngine(ENGINE_PATH)
    try:
        engine.start()
        # Red mates in one by dropping either back-rank chariot to rank 9.
        lines = engine.analyze("4k4/R8/1R6R/9/9/9/9/9/9/3K5 w - - 0 1", depth=6, multipv=1)
        assert lines
        assert lines[0].score_mate is not None and lines[0].score_mate > 0
    finally:
        engine.stop()


def test_multipv_setting_survives_repeated_analyses():
    """analyze() caches the MultiPV option; make sure the cache cannot go stale
    and silently return fewer lines than asked for."""
    engine = UCCIEngine(ENGINE_PATH)
    try:
        engine.start()
        assert len(engine.analyze(START_FEN, depth=6, multipv=3)) == 3
        assert len(engine.analyze(START_FEN, depth=6, multipv=1)) == 1
        assert len(engine.analyze(START_FEN, depth=6, multipv=3)) == 3
    finally:
        engine.stop()
