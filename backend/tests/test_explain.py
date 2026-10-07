"""Coaching-text tests.

The old explanation layer concatenated fragments and could praise and scold in
the same breath ("this is the engine's best move" followed by a hanging-piece
warning). These lock in the properties that make the text usable.
"""
from app.analysis.classify import classify_cp_loss
from app.analysis.explain import build_explanation, describe_piece
from app.xiangqi.board import Board, Move


def explain(fen, uci, cp_loss=0, best=None, matches_best=False, history=None, **kw):
    board = Board.from_fen(fen) if fen else Board.from_fen()
    # Replay the history so the board and the move list stay consistent.
    for played in history or []:
        board.apply_move(Move.from_uci(played))
    return build_explanation(
        board_before=board,
        move=Move.from_uci(uci),
        classification=classify_cp_loss(cp_loss),
        best_move_uci=best,
        played_matches_best=matches_best,
        move_history_before=history or [],
        **kw,
    )


def test_uses_chinese_notation_not_coordinates():
    out = explain(None, "h2e2", matches_best=True)
    assert out["move_chinese"] == "炮二平五"
    assert "炮二平五" in out["text"]
    assert "h2e2" not in out["text"]


def test_best_move_is_named_in_chinese():
    out = explain(None, "c3c4", cp_loss=60, best="h2e2")
    assert out["best_move_chinese"] == "炮二平五"
    assert "炮二平五" in (out["why_better"] or "")


def test_zero_loss_is_not_described_as_a_loss():
    """cp_loss 0 with a different engine pick must not read
    「最佳（损失约 0 分）」, which contradicts itself."""
    out = explain(None, "h0g2", cp_loss=0, best="g3g4")
    assert "损失约 0" not in out["text"]
    assert "同样好" in out["text"]
    assert out["why_better"] is None, "nothing is 'better' when the loss is zero"


def test_matching_the_engine_says_so_plainly():
    out = explain(None, "h2e2", matches_best=True, best="h2e2")
    assert "这正是引擎的首选" in out["text"]
    assert out["why_better"] is None


def test_blunder_gets_a_reason_to_prefer_the_engine_move():
    out = explain(None, "a0a1", cp_loss=400, best="h2e2")
    assert out["why_better"] is not None
    assert "引擎首选" in out["why_better"]


def test_opening_is_mentioned_once_not_twice():
    out = explain(None, "h2e2", matches_best=True)
    assert out["text"].count("中炮局") == 1


def test_leaving_theory_is_announced_only_on_the_diverging_ply():
    diverge = explain(None, "a0a1", cp_loss=50, best="h2e2", history=["h2e2", "h9g7"])
    assert "离开了" in diverge["text"]

    later = explain(
        None, "a1a2", cp_loss=50, best="h2e2",
        history=["h2e2", "h9g7", "a0a1", "b9c7"],
    )
    assert "离开了" not in later["text"], "should not keep nagging after divergence"


def test_terminal_checkmate_text_overrides_everything():
    out = explain(
        "4k4/R8/1R6R/9/9/9/9/9/9/3K5 w - - 0 1", "i7i9",
        cp_loss=0, best="b7b9", terminal_status="checkmate",
    )
    assert "绝杀" in out["text"]
    assert "损失" not in out["text"]
    assert out["why_better"] is None


def test_good_move_warnings_are_softened_not_contradictory():
    """A warning after a good move is framed as something to watch, so the
    paragraph never praises and scolds at the same time."""
    # Red chariot on a0 is genuinely hanging to the black chariot on a1.
    out = explain("3k5/9/9/9/9/9/9/9/r8/R3K4 w - - 0 1", "e0e1", matches_best=True)
    warnings = [s for s in out["text"].split() if "受攻" in s or "吃掉" in s or "要注意" in s]
    if warnings:
        assert "要注意" in out["text"]


def test_describe_piece_names_file_and_coordinate():
    board = Board.from_fen()
    # h2 is red's 二路炮.
    assert describe_piece(board, (7, 7)) == "二路炮（h2）"
    # h9 is black's ８路马.
    assert describe_piece(board, (0, 7)) == "８路马（h9）"


def test_tactics_carry_both_coordinate_and_chinese_labels():
    out = explain("3k5/9/9/9/9/9/9/9/r8/R3K4 w - - 0 1", "e0e1", matches_best=True)
    for tag in out["tactics"]:
        assert tag["square"]
        assert tag["square_chinese"]
        assert len(tag["targets"]) == len(tag["targets_chinese"])


def test_explanation_is_a_single_non_empty_paragraph():
    out = explain(None, "h2e2", matches_best=True)
    assert out["text"].strip()
    assert "\n" not in out["text"]


def test_attack_row_names_the_victim_and_is_embedded_in_the_paragraph():
    out = explain("4k4/9/9/9/R8/3n5/9/9/9/3K5 w - - 0 1", "a5d5", matches_best=True)
    rows = out["intents"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "attack"
    assert rows[0]["text"] == "威胁白吃对方的４路马（d4）"
    assert rows[0]["targets_chinese"] == ["４路马（d4）"]
    assert out["intent_text"] == "这步意在威胁白吃对方的４路马（d4）。"
    assert out["intent_text"] in out["text"]


def test_defended_attack_uses_the_net_gain_wording():
    # The victim is on e5 — black's ５路 — defended by the pawn on e6 (SEE 5.0).
    out = explain("4k4/9/9/4p4/4r4/9/9/9/2N6/3K5 w - - 0 1", "c1d3", matches_best=True)
    assert [r["text"] for r in out["intents"]] == ["威胁吃对方的５路车（e5），兑子后你净赚约 5 兵"]


def test_even_contact_uses_exchange_wording():
    # Same shape, but the victim is a horse: the trade is even (SEE 0.0).
    out = explain("4k4/9/9/4p4/4n4/9/9/9/2N6/3K5 w - - 0 1", "c1d3", matches_best=True)
    assert [r["text"] for r in out["intents"]] == ["邀兑对方的５路马（e5），对方有子保护"]


def test_small_edge_pressure_uses_the_probing_wording():
    # Taking the defended cannon nets half a pawn after the pawn recaptures.
    out = explain("4k4/9/9/4p4/4c4/9/9/9/2N6/3K5 w - - 0 1", "c1d3", matches_best=True)
    assert [r["text"] for r in out["intents"]] == ["先手瞄住对方的５路炮（e5），兑子你稍占便宜"]


def test_hollow_cannon_is_an_attack_row():
    # 空头炮 aims at the general, so the move also gives check — both facts
    # must appear, hollow cannon first.
    out = explain("3k5/3a5/9/9/9/C8/9/9/3K5/9 w - - 0 1", "a4d4", matches_best=True)
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["attack", "goal"]
    assert rows[0]["text"] == "架起空头炮，直指对方中路"
    assert rows[1]["text"] == "将军，抢得先手"
    assert out["intent_text"] == "这步意在架起空头炮，直指对方中路；将军，抢得先手。"


def test_defense_row_names_the_threatening_move():
    out = explain("3k5/9/9/9/9/2N6/9/9/r8/R3K4 w - - 0 1", "c4b2", matches_best=True)
    rows = out["intents"]
    assert len(rows) == 1
    assert rows[0]["kind"] == "defend"
    assert rows[0]["text"] == "保住九路车（a0），化解对方车１进１吃车的威胁"
    assert out["intent_text"] == "这步意在保住九路车（a0），化解对方车１进１吃车的威胁。"


def test_defend_by_capture_still_reads_the_threat_from_the_before_board():
    out = explain("3k5/9/9/9/9/9/1N7/9/r8/R3K4 w - - 0 1", "b3a1", matches_best=True)
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["defend", "goal"]
    assert rows[0]["text"] == "保住九路车（a0），化解对方车１进１吃车的威胁"
    assert rows[0]["targets_chinese"] == ["１路车（a1）"]  # read from the BEFORE board
    assert out["intent_text"] == "这步意在保住九路车（a0），化解对方车１进１吃车的威胁；吃掉对方的车。"


def test_escape_row_uses_the_origin_square():
    out = explain("4k4/9/9/9/9/9/9/3K5/r8/R8 w - - 0 1", "a0i0", matches_best=True)
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["defend", "goal"]
    assert rows[0]["text"] == "把受攻的九路车（a0）从对方攻击下走开"
    assert out["intent_text"] == "这步意在把受攻的九路车（a0）从对方攻击下走开；活通了车路，让车的出路更顺畅。"


def test_a_fork_merges_into_one_double_attack_row():
    out = explain("4k4/9/9/3n1c3/6r2/9/9/5N3/9/3K5 w - - 0 1", "f2e4", matches_best=True)
    rows = out["intents"]
    assert len(rows) == 1
    assert rows[0]["text"] == "形成双重攻击：对方的７路车（g5）和６路炮（f6）无法同时兼顾"
    assert rows[0]["targets_chinese"] == ["７路车（g5）", "６路炮（f6）"]


def test_blunder_still_gets_intents_without_praise():
    out = explain(None, "a0a1", cp_loss=400, best="h2e2")
    rows = out["intents"]
    assert [r["kind"] for r in rows] == ["goal"]
    assert out["intent_text"] == "这步意在把车从原位出动，加快大子的开发。"
    assert "稳健" not in out["text"]
    assert "大漏着" in out["text"]


def test_terminal_moves_have_no_intents():
    out = explain(
        "4k4/R8/1R6R/9/9/9/9/9/9/3K5 w - - 0 1", "i7i9",
        cp_loss=0, best="b7b9", terminal_status="checkmate",
    )
    assert out["intents"] == []
    assert out["intent_text"] is None
