"""Move-quality classification based on centipawn loss.

All evaluations are normalized to the perspective of the side that made the
move being judged (positive = good for the mover).
"""
from __future__ import annotations

from dataclasses import dataclass

MATE_SCORE = 100_000


def score_to_cp(score_cp: int | None, score_mate: int | None) -> int:
    """Collapse a (cp, mate) engine score pair into a single comparable centipawn
    value. Mate scores are mapped to large magnitudes, closer mates being more
    extreme, so they always dominate normal cp comparisons."""
    if score_mate is not None:
        if score_mate > 0:
            return MATE_SCORE - score_mate
        else:
            return -MATE_SCORE - score_mate
    return score_cp or 0


@dataclass
class Classification:
    label: str
    label_en: str
    color: str
    cp_loss: int


# Ordered thresholds (max cp_loss inclusive) -> (Chinese label, English label, UI color)
THRESHOLDS: list[tuple[int, str, str, str]] = [
    (0, "最佳", "Best", "#3aa15c"),
    (15, "优秀", "Excellent", "#5cb85c"),
    (40, "好棋", "Good", "#8bc34a"),
    (100, "不太准确", "Inaccuracy", "#f0ad4e"),
    (250, "失误", "Mistake", "#e07b39"),
]
BLUNDER = ("大漏着", "Blunder", "#d9534f")


def classify_cp_loss(cp_loss: int) -> Classification:
    loss = max(0, cp_loss)
    for max_loss, label, label_en, color in THRESHOLDS:
        if loss <= max_loss:
            return Classification(label=label, label_en=label_en, color=color, cp_loss=loss)
    label, label_en, color = BLUNDER
    return Classification(label=label, label_en=label_en, color=color, cp_loss=loss)


def to_red_perspective_cp(score_cp: int | None, score_mate: int | None, side_to_move: str) -> int:
    """Convert an engine score (always from the perspective of the side to
    move) into a value from RED's perspective, for a consistent eval bar."""
    cp = score_to_cp(score_cp, score_mate)
    return cp if side_to_move == "w" else -cp


def cp_loss_for_move(
    best_cp_before: int,
    played_cp_after_movers_pov: int,
    played_matches_best: bool,
) -> int:
    if played_matches_best:
        return 0
    return max(0, best_cp_before - played_cp_after_movers_pov)
