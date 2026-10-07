"""Turns classification + tactics + intents + opening context into coherent Chinese coaching.

Everything here is deterministic and rule-based — the facts come from the
engine's scores and the detectors in tactics.py / intent.py, and this module
only decides how to say them. Three principles:

* Never contradict itself. The old version could open with 「这正是引擎认为最好的
  一步」 and immediately warn about a hanging piece; warnings after a good move
  are now framed as things to watch rather than as faults.
* Say what a move DID, not just where it went. 「更好的选择是 a9 到 b9」 teaches
  nothing; naming the move in 记谱法 and giving the reason does.
* Say what the move was trying to DO. intent.py supplies the facts — the
  pieces it now attacks, the ones it saved, a 空头炮 — and this module renders
  them as short rows whose texts are also joined into one 「这步意在…」 sentence
  inside the paragraph.
"""
from __future__ import annotations

from ..xiangqi.board import Board, Move, other_side, piece_color
from ..xiangqi.movegen import is_in_check, piece_pseudo_moves
from ..xiangqi.notation import move_to_chinese, numeral, file_number
from .classify import Classification
from .intent import IntentTag, detect
from .openings import find_opening
from .tactics import TacticTag, all_tactics_for_side, piece_name, sq_name

# Ordering used when several problems exist at once — most urgent first.
_PROBLEM_PRIORITY = {"hanging": 0, "fork": 1, "hollow_cannon": 2, "cannon_threat": 3, "pin": 4}


def describe_piece(board: Board, sq: tuple[int, int]) -> str:
    """Name a piece by its file (in its owner's numbering) plus the coordinate,
    e.g. 七路兵（c4）. The file matches what the move list shows in 记谱法 and the
    coordinate matches the board's edge labels, so it can be found either way."""
    piece = board.piece_at(sq)
    if piece is None:
        return sq_name(sq)
    side = piece_color(piece)
    file_ch = numeral(file_number(sq[1], side), side)
    return f"{file_ch}路{piece_name(piece)}（{sq_name(sq)}）"


def _tag_key(tag: TacticTag) -> tuple:
    return (tag.kind, tag.piece_sq, tuple(sorted(tag.target_sqs)))


def _tactic_sentence(board: Board, tag: TacticTag, soften: bool) -> str:
    """One sentence describing a problem the mover now faces. `soften` phrases
    it as something to keep an eye on rather than as a mistake."""
    who = describe_piece(board, tag.piece_sq)
    lead = "要注意，" if soften else ""

    if tag.kind == "hanging":
        targets = "、".join(describe_piece(board, s) for s in tag.target_sqs)
        loss = tag.detail.get("see_loss")
        if tag.detail.get("defended"):
            return f"{lead}你的{who}虽有子防守，但对方可以用较小的子力换取，兑换下来你要亏约 {loss} 个兵的子力（攻击来自{targets}）。"
        return f"{lead}你的{who}正被攻击且无子防守，会被直接吃掉，损失约 {loss} 个兵的子力（攻击来自{targets}）。"

    if tag.kind == "pin":
        if tag.detail.get("by_facing"):
            return f"{lead}你的{who}被将帅照面牵制，一动就会造成白脸将，等于完全走不动。"
        return f"{lead}你的{who}被牵制，一走将/帅就要被将军，目前无法动弹。"

    if tag.kind == "fork":
        targets = "、".join(describe_piece(board, s) for s in tag.target_sqs)
        return f"{lead}对方的{who}形成双重攻击，同时瞄准{targets}，你无法同时保住两子。"

    if tag.kind == "cannon_threat":
        targets = "、".join(describe_piece(board, s) for s in tag.target_sqs)
        return f"{lead}对方的{who}可以隔子打到{targets}。"

    if tag.kind == "hollow_cannon":
        return f"{lead}对方的{who}形成空头炮，正对你的将/帅，中路压力很大。"

    return ""


def _problems_for(board: Board, mover: str) -> list[TacticTag]:
    """Tactics on `board` that favour the mover's opponent, i.e. the mover's
    problems, most urgent first."""
    opponent = other_side(mover)
    tags = [t for t in all_tactics_for_side(board, opponent) if t.side == opponent]
    return sorted(tags, key=lambda t: _PROBLEM_PRIORITY.get(t.kind, 9))


def _gains_for(board: Board, mover: str) -> list[TacticTag]:
    """Tactics on `board` that favour the mover."""
    return [t for t in all_tactics_for_side(board, mover) if t.side == mover]


# Opening squares of the pieces that matter for development (车/马/炮). A move
# off one of these is 出动大子 — the single most common merit of a quiet opening
# move, and previously the case that produced no explanation at all.
_START_SQUARES: dict[str, dict[str, set[tuple[int, int]]]] = {
    "w": {"R": {(9, 0), (9, 8)}, "N": {(9, 1), (9, 7)}, "C": {(7, 1), (7, 7)}},
    "b": {"R": {(0, 0), (0, 8)}, "N": {(0, 1), (0, 7)}, "C": {(2, 1), (2, 7)}},
}


def _chariot_mobility(board: Board, side: str) -> int:
    """Total squares this side's chariots can reach — the usual proxy for 车路
    being open. A quiet move that raises it has 活通车路."""
    total = 0
    for r in range(10):
        for c in range(9):
            p = board.grid[r][c]
            if p is not None and piece_color(p) == side and p.upper() == "R":
                total += len(piece_pseudo_moves(board, (r, c)))
    return total


def _move_facts(board_before: Board, move: Move) -> dict:
    """Concrete, checkable things a move does."""
    piece = board_before.piece_at(move.from_sq)
    mover = piece_color(piece)
    kind = piece.upper()
    captured = board_before.piece_at(move.to_sq)
    after = board_before.clone()
    after.apply_move(move)

    before_problems = {_tag_key(t) for t in _problems_for(board_before, mover)}
    after_problems = _problems_for(after, mover)
    before_gains = {_tag_key(t) for t in _gains_for(board_before, mover)}
    after_gains = _gains_for(after, mover)

    starts = _START_SQUARES[mover].get(kind, set())
    if kind == "P":
        crossed_river = (
            move.from_sq[0] >= 5 and move.to_sq[0] <= 4 if mover == "w"
            else move.from_sq[0] <= 4 and move.to_sq[0] >= 5
        )
    else:
        crossed_river = False

    return {
        "board_after": after,
        "piece": piece,
        "kind": kind,
        "captured": captured,
        "gives_check": is_in_check(after, other_side(mover)),
        "new_problems": [t for t in after_problems if _tag_key(t) not in before_problems],
        "all_problems": after_problems,
        "resolved_problems": before_problems - {_tag_key(t) for t in after_problems},
        "new_gains": [t for t in after_gains if _tag_key(t) not in before_gains],
        # Positional facts — what a quiet move accomplishes.
        "develops": move.from_sq in starts and move.to_sq not in starts,
        "crossed_river": crossed_river,
        "to_centre_file": move.to_sq[1] == 4,
        "piece_mobility_gain": (
            len(piece_pseudo_moves(after, move.to_sq))
            - len(piece_pseudo_moves(board_before, move.from_sq))
        ),
        "chariot_mobility_gain": _chariot_mobility(after, mover) - _chariot_mobility(board_before, mover),
    }


def _format_pawns(value: float) -> str:
    """A pawn count for prose: one decimal, with a trailing .0 dropped."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def _row(
    kind: str,
    text: str,
    board: Board,
    piece: str,
    piece_sq: tuple[int, int],
    target_sqs: list[tuple[int, int]],
) -> dict:
    """One intent row in its wire shape; squares are named from `board`, which
    is the board the wording describes (after the move for attacks, before it
    for defenses)."""
    return {
        "kind": kind,
        "text": text,
        "piece": piece,
        "piece_name": piece_name(piece),
        "square": sq_name(piece_sq),
        "square_chinese": describe_piece(board, piece_sq),
        "targets": [sq_name(s) for s in target_sqs],
        "targets_chinese": [describe_piece(board, s) for s in target_sqs],
    }


def _attack_row(board_after: Board, tag: IntentTag) -> dict:
    """One attack: what the move now threatens, and how real the gain is.
    Never phrased as a threat when the exchange only offers equal value."""
    victim = describe_piece(board_after, tag.target_sqs[0])
    if tag.detail["tier"] == "win":
        if tag.detail["defended"]:
            text = f"威胁吃对方的{victim}，兑子后你净赚约 {_format_pawns(tag.detail['see'])} 兵"
        else:
            text = f"威胁白吃对方的{victim}"
    elif tag.detail["see"] > 0:
        text = f"先手瞄住对方的{victim}，兑子你稍占便宜"
    else:
        text = f"邀兑对方的{victim}，对方有子保护"
    return _row("attack", text, board_after, tag.piece, tag.piece_sq, tag.target_sqs)


def _defend_row(board_before: Board, tag: IntentTag) -> dict:
    """One defense. The saved piece AND the threatener are described from the
    before board — the threatener may be gone by now (captured by this very
    move), but the threat it posed is still the reason for the move."""
    who = describe_piece(board_before, tag.piece_sq)
    if tag.detail["escape"]:
        text = f"把受攻的{who}从对方攻击下走开"
    else:
        threat = move_to_chinese(board_before, Move.from_uci(tag.detail["threat_uci"]))
        text = f"保住{who}，化解对方{threat}吃{piece_name(tag.piece)}的威胁"
    return _row("defend", text, board_before, tag.piece, tag.piece_sq, tag.target_sqs)


def _intent_rows(
    board_before: Board,
    board_after: Board,
    move: Move,
    tags: list[IntentTag],
    goal_fragments: list[str],
    new_gains: list[TacticTag],
) -> list[dict]:
    """The rows behind 「这步意在…」: attacks (a fork merged into one row),
    空头炮, defenses, then the positional goal the move pursued."""
    rows: list[dict] = []

    # Two or more wins from the same attacker are one fork, not two threats:
    # the opponent cannot answer both, which is the fact worth saying.
    attacks = [t for t in tags if t.kind == "attack"]
    win_groups: dict[tuple[int, int], list[IntentTag]] = {}
    for tag in attacks:
        if tag.detail["tier"] == "win":
            win_groups.setdefault(tag.piece_sq, []).append(tag)

    merged: set[tuple[int, int]] = set()
    for tag in attacks:
        group = win_groups.get(tag.piece_sq, [])
        if len(group) < 2:
            rows.append(_attack_row(board_after, tag))
        elif tag.piece_sq not in merged:
            merged.add(tag.piece_sq)
            victims = [g.target_sqs[0] for g in group]
            names = "和".join(describe_piece(board_after, s) for s in victims)
            rows.append(_row(
                "attack", f"形成双重攻击：对方的{names}无法同时兼顾",
                board_after, tag.piece, tag.piece_sq, victims,
            ))

    for tag in new_gains:
        if tag.kind == "hollow_cannon":
            rows.append(_row(
                "attack", "架起空头炮，直指对方中路",
                board_after, tag.piece, tag.piece_sq, tag.target_sqs,
            ))

    for tag in tags:
        if tag.kind == "defend":
            rows.append(_defend_row(board_before, tag))

    if goal_fragments:
        rows.append(_row(
            "goal", "，".join(goal_fragments),
            board_after, board_after.piece_at(move.to_sq), move.to_sq, [],
        ))
    return rows


def _goal_fragments(
    board_before: Board,
    move: Move,
    facts: dict,
    opening: dict,
    good_move: bool,
    has_tactical_facts: bool,
) -> list[str]:
    """What the move set out to do, as short fragments.

    Tactical gains have their own rows now, so this covers the action facts
    (check, capture) plus the quiet positional reasons — 出动大子, 过河,
    活通车路 — a move would otherwise not get. The book line and the generic
    稳健 fallback are only worth saying when the move was good and no tactical
    row already told the story.
    """
    piece = board_before.piece_at(move.from_sq)
    parts: list[str] = []
    if facts["gives_check"]:
        parts.append("将军，抢得先手")
    if facts["captured"] is not None:
        parts.append(f"吃掉对方的{piece_name(facts['captured'])}")

    if not parts:
        # Quiet move: say what it does positionally. Each of these is a fact
        # checked against the board, not a generic platitude.
        if facts["kind"] == "C" and facts["to_centre_file"]:
            parts.append("把炮架到中路，正对对方中卒，是中炮体系的核心一着")
        elif facts["develops"]:
            parts.append(f"把{piece_name(piece)}从原位出动，加快大子的开发")
        elif facts["crossed_river"]:
            parts.append("兵过河，威力大增，可以横向活动")
        elif facts["chariot_mobility_gain"] >= 3:
            parts.append("活通了车路，让车的出路更顺畅")
        elif facts["piece_mobility_gain"] >= 3:
            parts.append(f"让这只{piece_name(piece)}的活动空间明显变大")
        elif good_move and not has_tactical_facts and opening.get("in_book") and opening.get("name"):
            parts.append(f"稳稳走在「{opening['name']}」的主流路线上")
        elif good_move and not has_tactical_facts:
            parts.append("是一步稳健的调整，没有立即的战术收获，价值在于改善子力位置")
    return parts


def _build_why_better(
    board_before: Board,
    played: Move,
    best_uci: str,
    played_facts: dict,
) -> str | None:
    """Explain what the engine's choice does that the played move does not."""
    try:
        best = Move.from_uci(best_uci)
    except (ValueError, IndexError):
        return None
    if board_before.piece_at(best.from_sq) is None:
        return None

    best_chinese = move_to_chinese(board_before, best)
    best_facts = _move_facts(board_before, best)

    reasons = []
    if best_facts["captured"] is not None:
        reasons.append(f"可以直接吃掉对方的{piece_name(best_facts['captured'])}")
    if best_facts["gives_check"] and not played_facts["gives_check"]:
        reasons.append("先手将军，抢到主动")

    # Problems the played move allowed that the engine's move would have avoided.
    best_problem_keys = {_tag_key(t) for t in best_facts["all_problems"]}
    avoided = [t for t in played_facts["all_problems"] if _tag_key(t) not in best_problem_keys]
    for tag in avoided[:1]:
        if tag.kind == "hanging":
            reasons.append(f"同时保住了{describe_piece(board_before, tag.piece_sq)}，不会像实战那样白丢子力")
        elif tag.kind == "hollow_cannon":
            reasons.append("不会让对方架起空头炮")
        elif tag.kind == "fork":
            reasons.append("避开了对方的双重攻击")
        elif tag.kind == "pin":
            reasons.append("避免了被牵制")
        elif tag.kind == "cannon_threat":
            reasons.append("回避了对方炮的隔子攻击")

    for tag in best_facts["new_gains"][:1]:
        if tag.kind == "hollow_cannon":
            reasons.append("并且架起空头炮压制中路")
        elif tag.kind == "fork":
            reasons.append("并且形成双重攻击")

    if not reasons:
        return f"引擎首选 {best_chinese}，在后续变化中能保持更好的子力与位置。"
    return f"引擎首选 {best_chinese}：" + "，".join(reasons) + "。"


def build_explanation(
    board_before: Board,
    move: Move,
    classification: Classification,
    best_move_uci: str | None,
    played_matches_best: bool,
    move_history_before: list[str],
    terminal_status: str | None = None,
    repetition_note: str | None = None,
) -> dict:
    """Assemble the full coaching payload for one move."""
    mover = piece_color(board_before.piece_at(move.from_sq))
    move_chinese = move_to_chinese(board_before, move)
    facts = _move_facts(board_before, move)
    board_after = facts["board_after"]
    opening = find_opening(move_history_before + [move.to_uci()])

    best_chinese = None
    if best_move_uci:
        try:
            candidate = Move.from_uci(best_move_uci)
            if board_before.piece_at(candidate.from_sq) is not None:
                best_chinese = move_to_chinese(board_before, candidate)
        except (ValueError, IndexError):
            best_chinese = None

    good_move = played_matches_best or classification.cp_loss <= 40
    # A cp_loss of 0 means the move is rated the same as the engine's pick, so
    # there is nothing "better" to explain — only an equally good alternative.
    equal_to_best = not played_matches_best and classification.cp_loss == 0
    why_better = (
        _build_why_better(board_before, move, best_move_uci, facts)
        if not played_matches_best and best_move_uci and classification.cp_loss > 0
        else None
    )

    # The intent layer: what the move attacked or saved, plus the positional
    # goal. Only a live position has intents — a finished game has no next move
    # to intend anything with.
    intent_rows: list[dict] = []
    intent_text: str | None = None
    if terminal_status is None:
        tags = detect(board_before, move)
        new_gains = facts["new_gains"]
        has_tactical = bool(tags) or any(t.kind == "hollow_cannon" for t in new_gains)
        goal_fragments = _goal_fragments(
            board_before, move, facts, opening, good_move, has_tactical
        )
        intent_rows = _intent_rows(
            board_before, board_after, move, tags, goal_fragments, new_gains
        )
        if intent_rows:
            intent_text = "这步意在" + "；".join(r["text"] for r in intent_rows) + "。"

    sentences: list[str] = []

    # 1. Terminal results dominate everything else.
    if terminal_status == "checkmate":
        sentences.append(f"{move_chinese}——绝杀！这一步将死对方，本局结束。")
    elif terminal_status == "stalemate":
        sentences.append(f"{move_chinese}——困毙对方，对方无子可动，本局结束。")
    elif terminal_status in ("perpetual_loss", "draw_repetition"):
        sentences.append(f"{move_chinese}。{repetition_note or '局面重复。'}")
    else:
        # 2. Quality verdict.
        if played_matches_best:
            sentences.append(f"{move_chinese}，这正是引擎的首选。")
        elif equal_to_best:
            alt = f"引擎首选 {best_chinese}，" if best_chinese else ""
            sentences.append(f"{move_chinese}，与最佳着法评价相同，是同样好的一步（{alt}两者皆可）。")
        else:
            sentences.append(
                f"{move_chinese}，{classification.label}"
                f"（较最佳着法损失约 {classification.cp_loss} 分）。"
            )
        if intent_text:
            sentences.append(intent_text)

    # 3. What the position now demands. After a good move these are framed as
    #    things to watch, so the paragraph never praises and scolds at once.
    if terminal_status is None:
        problems = facts["new_problems"] or facts["all_problems"]
        for tag in problems[:2]:
            text = _tactic_sentence(board_after, tag, soften=good_move)
            if text:
                sentences.append(text)

        # 4. The better alternative and why.
        if why_better:
            sentences.append(why_better)

        # 5. Opening context — named once while in book, and the departure from
        #    theory mentioned only on the ply it actually happens.
        if opening.get("name"):
            if opening.get("in_book"):
                sentences.append(f"布局仍在「{opening['name']}」之内。{opening.get('note') or ''}".strip())
            elif opening.get("left_book_now"):
                sentences.append(f"从这一步起，你离开了「{opening['name']}」的常见理论。")

        if repetition_note:
            sentences.append(repetition_note)

    return {
        "text": " ".join(s for s in sentences if s),
        "move_chinese": move_chinese,
        "best_move_chinese": best_chinese,
        "why_better": why_better,
        "intents": intent_rows,
        "intent_text": intent_text,
        "tactics": [
            {
                "kind": t.kind,
                "side": t.side,
                "piece": t.piece,
                "piece_name": piece_name(t.piece),
                "square": sq_name(t.piece_sq),
                "square_chinese": describe_piece(board_after, t.piece_sq),
                "targets": [sq_name(s) for s in t.target_sqs],
                "targets_chinese": [describe_piece(board_after, s) for s in t.target_sqs],
            }
            for t in facts["all_problems"]
        ],
        "opening": opening,
    }
