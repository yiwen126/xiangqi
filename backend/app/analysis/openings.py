"""A curated Xiangqi opening book, matched by move-sequence prefix.

Moves are UCI-style coordinates (file a-i, rank 0-9, rank 0 = red's back rank)
matching Move.to_uci(). Every line's Chinese name is verified against
xiangqi.notation in the test-suite, so a mislabelled entry fails CI rather than
teaching the wrong name.

Not exhaustive — enough to name the opening being played, quote its plan, and
flag the ply where the game leaves known theory.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OpeningLine:
    name: str
    moves: list[str]
    note: str


# fmt: off
OPENING_BOOK: list[OpeningLine] = [
    # --- 中炮体系 (central cannon) ---
    OpeningLine("中炮局", ["h2e2"],
                "炮二平五。红方右炮平中，直接瞄准中卒，是最主流、进攻性最强的开局。"),
    OpeningLine("中炮局", ["b2e2"],
                "炮八平五。红方左炮平中，同属中炮体系，子力展开方向与右中炮镜像。"),
    OpeningLine("中炮对屏风马", ["h2e2", "h9g7"],
                "炮二平五 马８进７。黑方跳右马，準备屏风马双马护中卒，是应对中炮最稳健的布局。"),
    OpeningLine("中炮对屏风马", ["h2e2", "h9g7", "h0g2"],
                "红方马二进三正起，稳步展开，为直车出动做準备。"),
    OpeningLine("中炮直车对屏风马", ["h2e2", "h9g7", "h0g2", "i9h9"],
                "黑方车９平８抢占直线，双方进入中炮对屏风马的主流对抗。"),
    OpeningLine("中炮直车对屏风马", ["h2e2", "h9g7", "h0g2", "i9h9", "i0h0"],
                "红方车一平二形成直车，双方各占一条直线，是最经典的对攻阵形。"),
    OpeningLine("中炮直车对屏风马", ["h2e2", "h9g7", "h0g2", "i9h9", "i0h0", "b9c7"],
                "黑方马２进３补齐屏风马，阵形工整，中卒得到双马保护。"),
    OpeningLine("中炮对反宫马", ["h2e2", "b9c7", "h0g2", "h7f7"],
                "黑方炮８平６形成反宫马（夹炮屏风），炮位于两士之间，阵形富有弹性。"),
    OpeningLine("中炮对单提马", ["h2e2", "b9a7"],
                "黑方马２进１屈边马（单提马），阵形紧凑但边马活动范围较小。"),
    OpeningLine("中炮对进左马", ["h2e2", "b9c7"],
                "黑方马２进３先跳左马，保留转屏风马或反宫马的选择。"),

    # --- 仙人指路 (pawn opening) ---
    OpeningLine("仙人指路", ["c3c4"],
                "兵七进一。挺七兵，含蓄灵活，保留转中炮、飞相、起马等多种可能。"),
    OpeningLine("仙人指路", ["g3g4"],
                "兵三进一。挺三兵，同为仙人指路，展开方向与挺七兵相反。"),
    OpeningLine("对兵局", ["c3c4", "g6g5"],
                "兵七进一 卒７进１。双方对挺兵卒，形成对兵局，是最讲究次序的开局之一。"),
    OpeningLine("仙人指路对中炮", ["c3c4", "h7e7"],
                "黑方炮８平５还中炮，以攻对攻，抢夺中路主动权。"),
    OpeningLine("仙人指路对卒底炮", ["c3c4", "h7c7"],
                "黑方炮８平３卒底炮，直接顶住红方七路兵头，针锋相对。"),

    # --- 飞相局 (elephant opening) ---
    OpeningLine("飞相局", ["g0e2"],
                "相三进五。红方起右相，稳健防守型开局，阵形厚实少弱点。"),
    OpeningLine("飞相局", ["c0e2"],
                "相七进五。红方起左相，同为飞相局，与右相镜像。"),
    OpeningLine("飞相对中炮", ["g0e2", "h7e7"],
                "黑方炮８平５还架中炮，以中路进攻对抗红方的稳健阵形。"),
    OpeningLine("飞相对左中炮", ["g0e2", "b7e7"],
                "黑方炮２平５从另一侧架中炮，子力展开方向不同。"),

    # --- 起马局 (horse opening) ---
    OpeningLine("起马局", ["h0g2"],
                "马二进三。红方右马正起，含蓄灵活，可转入多种阵型。"),
    OpeningLine("起马局", ["b0c2"],
                "马八进七。红方左马正起，同为起马局。"),
    OpeningLine("起马对进卒", ["h0g2", "g6g5"],
                "黑方卒７进１挺卒制马，限制红方三路马的活动。"),

    # --- 过宫炮 / 士角炮 (cannon to the far palace file / advisor corner) ---
    OpeningLine("过宫炮", ["h2d2"],
                "炮二平六。炮横越过宫，攻击性强，但左翼稍显空虚。"),
    OpeningLine("过宫炮", ["b2f2"],
                "炮八平四。左炮过宫，与右过宫炮镜像。"),
    OpeningLine("士角炮", ["h2f2"],
                "炮二平四。炮镇士角，阵形灵活，常与起马配合。"),
    OpeningLine("士角炮", ["b2d2"],
                "炮八平六。左士角炮，同样是灵活的转换型开局。"),

    # --- 其他 ---
    OpeningLine("边炮局", ["h2i2"],
                "炮二平一。炮平边路，冷门但富有变化。"),
    OpeningLine("仙人指路对进马", ["c3c4", "b9c7"],
                "黑方马２进３正起，以稳健的马位应对红方的挺兵试探。"),
]
# fmt: on


def _best_match(move_history: list[str]) -> tuple[OpeningLine | None, int]:
    """Longest book line agreeing with `move_history` over their common prefix."""
    best: OpeningLine | None = None
    best_len = 0
    for line in OPENING_BOOK:
        n = min(len(line.moves), len(move_history))
        if n == 0:
            continue
        if line.moves[:n] == move_history[:n] and n > best_len:
            best = line
            best_len = n
    return best, best_len


def is_in_book(move_history: list[str]) -> bool:
    """True while every move played so far still follows some known line."""
    if not move_history:
        return True
    best, matched = _best_match(move_history)
    return best is not None and matched == len(move_history)


def find_opening(move_history: list[str]) -> dict:
    """Describe the opening for the given UCI move history.

    `in_book` is True while the game still follows a known line. `left_book_now`
    is True ONLY on the exact ply that diverged — the previous ply was still in
    book and this one is not — so the coach mentions leaving theory once instead
    of repeating it for the rest of the game.
    """
    best, matched = _best_match(move_history)
    if best is None:
        return {
            "name": None, "note": None, "in_book": False,
            "matched_plies": 0, "left_book_now": False,
        }

    in_book = matched == len(move_history)
    was_in_book = is_in_book(move_history[:-1]) if move_history else True
    return {
        "name": best.name,
        "note": best.note,
        "in_book": in_book,
        "matched_plies": matched,
        "left_book_now": (not in_book) and was_in_book,
    }
