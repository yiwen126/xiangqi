import pytest

from app.analysis.classify import classify_cp_loss, cp_loss_for_move, score_to_cp, to_red_perspective_cp


@pytest.mark.parametrize("loss,expected_label", [
    (0, "最佳"),
    (10, "优秀"),
    (30, "好棋"),
    (80, "不太准确"),
    (200, "失误"),
    (500, "大漏着"),
])
def test_classify_thresholds(loss, expected_label):
    assert classify_cp_loss(loss).label == expected_label


def test_negative_loss_clamped_to_zero():
    c = classify_cp_loss(-50)
    assert c.cp_loss == 0
    assert c.label == "最佳"


def test_cp_loss_for_move_matches_best():
    assert cp_loss_for_move(100, -999, played_matches_best=True) == 0


def test_cp_loss_for_move_computes_delta():
    assert cp_loss_for_move(100, 40, played_matches_best=False) == 60


def test_score_to_cp_mate():
    assert score_to_cp(None, 3) > score_to_cp(None, 10)
    assert score_to_cp(None, -1) < score_to_cp(None, 1)


def test_to_red_perspective():
    assert to_red_perspective_cp(50, None, "w") == 50
    assert to_red_perspective_cp(50, None, "b") == -50
