"""Single-game session: board state + engine analysis orchestration.

Personal tool, single user, one game in flight. The session may own an
auto-saving `GameStore`: every mutation mirrors the applied line into
`<store>/<id>.json`, lazily creating the record on the first move. With
`store=None` the session is purely in memory, which is what tests and an
engine-only setup use.

A lock guards the session because FastAPI runs sync endpoints in a threadpool,
so two overlapping requests would otherwise interleave board mutations (and
writes of the record).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime

from .analysis.classify import (
    MATE_SCORE,
    classify_cp_loss,
    cp_loss_for_move,
    score_to_cp,
    to_red_perspective_cp,
)
from .analysis.explain import build_explanation
from .engine.ucci import PvLine, UCCIEngine
from .library.records import (
    FORMAT_NAME,
    FORMAT_VERSION,
    GameRecord,
    RecordError,
    now_iso,
)
from .library.store import GameStore, StoreError
from .xiangqi.board import RED, START_FEN, Board, Move, other_side
from .xiangqi.movegen import is_in_check
from .xiangqi.notation import move_to_chinese, moves_to_chinese
from .xiangqi.repetition import evaluate_repetition, repetition_warning
from .xiangqi.rules import find_legal_move, game_status

DEPTH = int(os.environ.get("ENGINE_DEPTH", "14"))
MULTIPV = int(os.environ.get("ENGINE_MULTIPV", "3"))
PV_PLIES = 6  # how much of each principal variation to show
FOLLOW_UP_PLIES = 4  # how much of the after-move principal variation to show
PASSING_PLAN_STEPS = 10  # how many consecutive own moves the opponent-passes line shows


class IllegalMoveError(ValueError):
    pass


@dataclass(frozen=True)
class _ReplayedGame:
    """A saved line replayed onto a fresh board: everything the session state
    a record defines. Built by `_replay_record` without touching the session,
    so a record that fails to replay can never half-load it."""

    board: Board
    start_fen: str
    move_history: list[str]
    move_notes: list[str]
    game_note: str
    position_keys: list[str]
    move_sides: list[str]
    move_gave_check: list[bool]


class GameSession:
    def __init__(self, engine: UCCIEngine, store: GameStore | None = None):
        self.engine = engine
        # The library this session auto-saves into; None keeps it in memory.
        self.store = store
        self.lock = threading.RLock()
        self.start_fen = Board.from_fen().to_fen()
        self.board = Board.from_fen()
        self.move_history: list[str] = []
        # Moves undone from the end of move_history, most-recently-undone last —
        # a LIFO redo stack. Cleared whenever a genuinely new move is played.
        self.redo_stack: list[str] = []
        # Notes are parallel to the move stacks so a note can never drift to a
        # different ply: move_notes[i] belongs to move_history[i], redo_notes is
        # a LIFO matching redo_stack, and game_note covers the whole game.
        self.move_notes: list[str] = []
        self.redo_notes: list[str] = []
        self.game_note = ""
        # Repetition bookkeeping, parallel to move_history.
        self.position_keys: list[str] = [self.board.position_key()]
        self.move_sides: list[str] = []
        self.move_gave_check: list[bool] = []
        # Analysis of the current position, reused as the "before" search of the
        # next move so a normal move costs one search instead of two.
        self._cached_lines: list[PvLine] | None = None
        # Library identity of the game in flight, filled in by the first
        # `_persist` (or by opening/importing a record); all None until then.
        self.record_id: str | None = None
        self.record_name: str | None = None
        self.created_at: str | None = None
        self.saved_at: str | None = None
        self.save_error: str | None = None

    # ---------- engine plumbing ----------

    def new_game(self, fen: str | None = None) -> None:
        self.board = Board.from_fen(fen) if fen else Board.from_fen()
        self.start_fen = self.board.to_fen()
        self.move_history = []
        self.redo_stack = []
        self.move_notes = []
        self.redo_notes = []
        self.game_note = ""
        self.position_keys = [self.board.position_key()]
        self.move_sides = []
        self.move_gave_check = []
        self._cached_lines = None
        # A new game is a new library entry: releasing the old identity is what
        # keeps its first move from overwriting the previous game's file.
        self.record_id = None
        self.record_name = None
        self.created_at = None
        self.saved_at = None
        self.save_error = None
        if self.engine.is_running():
            self.engine.new_game()

    def current_lines(self) -> list[PvLine]:
        """Analyse the live position, reusing the cached search when valid.

        The full move list is sent rather than just the current FEN so the engine
        can see repetitions — without it Pikafish cannot apply the 长将 rules and
        may recommend a perpetual-check line that is actually a loss.
        """
        if self._cached_lines is not None:
            return self._cached_lines
        if not self.engine.is_running():
            return []
        if self._is_terminal():
            self._cached_lines = []
            return []
        lines = self.engine.analyze(
            self.start_fen, moves=list(self.move_history), depth=DEPTH, multipv=MULTIPV
        )
        self._cached_lines = lines
        return lines

    def _is_terminal(self) -> bool:
        return game_status(self.board)["status"] != "ongoing"

    # ---------- status ----------

    def _repetition_verdict(self):
        return evaluate_repetition(self.position_keys, self.move_sides, self.move_gave_check)

    def status_payload(self) -> dict:
        """Game status, with the Chinese repetition rules layered on top of
        checkmate/stalemate."""
        base = game_status(self.board)
        if base["status"] == "ongoing":
            verdict = self._repetition_verdict()
            if verdict is not None:
                return {
                    "status": verdict.status,
                    "winner": verdict.winner,
                    "in_check": base["in_check"],
                    "result_note": verdict.note,
                }
            return {**base, "result_note": None}
        note = "将死，本局结束。" if base["status"] == "checkmate" else "困毙（无子可动），本局结束。"
        return {**base, "result_note": note}

    def position_payload(self) -> dict:
        status = self.status_payload()
        lines = self.current_lines()
        return {
            "fen": self.board.to_fen(),
            "side_to_move": self.board.side_to_move,
            "game_status": status["status"],
            "in_check": status["in_check"],
            "winner": status["winner"],
            "result_note": status.get("result_note"),
            "move_history": list(self.move_history),
            "move_history_chinese": self._history_chinese(),
            "future_moves": list(reversed(self.redo_stack)),
            **self._notes_payload(),
            **self._record_fields(),
            "lines": [_pv_out(line) for line in lines],
        }

    def _history_chinese(self) -> list[str]:
        return moves_to_chinese(Board.from_fen(self.start_fen), self.move_history)

    # ---------- notes ----------

    def line_notes(self) -> list[str]:
        """Every ply's note in play order — the applied line, then the redo
        branch — exactly parallel to move_history + future_moves."""
        return self.move_notes + list(reversed(self.redo_notes))

    def set_note(self, ply: int | None, text: str) -> dict:
        """Write a note on the 1-based ply of the whole line (the applied line
        first, then the redo branch in play order), or the whole-game note when
        `ply` is None. A note may address a ply that is currently undone: it
        rides back into place on 重做 and dies with the branch on a new move."""
        with self.lock:
            if ply is None:
                self.game_note = text
            elif 1 <= ply <= len(self.move_history):
                self.move_notes[ply - 1] = text
            elif len(self.move_history) < ply <= len(self.move_history) + len(self.redo_stack):
                k = ply - len(self.move_history)  # 1-based index into the branch
                self.redo_notes[len(self.redo_stack) - k] = text
            else:
                raise IllegalMoveError(f"无效的步数：{ply}")
            self._persist()
            return {**self._notes_payload(), **self._record_fields()}

    def _notes_payload(self) -> dict:
        return {"notes": self.line_notes(), "game_note": self.game_note}

    # ---------- library: auto-save, open, import ----------

    def _record_fields(self) -> dict:
        """The record identity as the wire layer reports it. Merged into both
        `position_payload()` and the move result."""
        return {
            "game_id": self.record_id,
            "game_name": self.record_name,
            "saved_at": self.saved_at,
            "save_error": self.save_error,
        }

    def _persist(self, default_name: str | None = None) -> None:
        """Mirror the applied line into the store, creating the record on the
        first real move. Never raises: 自动保存 must never cost the player a
        move, so a failed write lands in `save_error` and the session keeps
        playing from memory. The record deliberately carries no engine output —
        it is large, recomputable, and would make an exported file brittle.

        The file always equals the applied line, so 悔棋 writes too: an empty
        line replaces the old moves. Only *creating* a record needs a move —
        that is what keeps repeated 新对局 from littering the library.

        Called under the session lock by every mutation."""
        if self.store is None:
            return
        if self.record_id is None and not self.move_history:
            return
        try:
            if self.record_id is None:
                self.record_id = self.store.new_id()
                self.created_at = now_iso()
                self.record_name = (
                    self.record_name
                    or default_name
                    or f"{datetime.now():%Y-%m-%d %H:%M} 对局"
                )
            status = self.status_payload()  # board rules only — no engine call
            record = GameRecord(
                format=FORMAT_NAME,
                version=FORMAT_VERSION,
                id=self.record_id,
                name=self.record_name,
                created_at=self.created_at,
                updated_at=now_iso(),
                start_fen=self.start_fen,
                moves=list(self.move_history),
                notes=list(self.move_notes),
                game_note=self.game_note,
                result=status["status"],
                winner=status["winner"],
            )
            saved = self.store.save(record)
            self.saved_at = saved.updated_at
            self.save_error = None
        except (RecordError, StoreError, OSError) as exc:
            self.save_error = str(exc)

    def _replay_record(self, record: GameRecord) -> _ReplayedGame:
        """Replay `record` onto a scratch board, validating every ply first.

        Pure: it returns a complete `_ReplayedGame` or raises, so a file that
        fails half way through cannot leave the session in a mixed state.
        `find_legal_move` proves each move legal against the position it was
        played in; the round-trip check catches strings `Move.from_uci` would
        silently accept (it truncates "h2e2x") or reinterpret (out-of-range
        coordinates), which would otherwise reach the engine as a bogus
        `position ... moves` token.
        """
        start_fen = record.start_fen or START_FEN
        board = Board.from_fen(start_fen)
        history: list[str] = []
        notes: list[str] = []
        sides: list[str] = []
        checks: list[bool] = []
        keys = [board.position_key()]
        for n, uci in enumerate(record.moves, start=1):
            try:
                move = Move.from_uci(uci)
            except (ValueError, IndexError) as exc:
                raise RecordError(f"第 {n} 步着法不合法：{uci}") from exc
            if move.to_uci() != uci:
                raise RecordError(f"第 {n} 步着法不合法：{uci}")
            legal = find_legal_move(board, move)
            if legal is None:
                raise RecordError(f"第 {n} 步着法不合法：{uci}")
            mover = board.side_to_move
            board.apply_move(legal)
            history.append(uci)
            notes.append(record.notes[n - 1] if n <= len(record.notes) else "")
            sides.append(mover)
            checks.append(is_in_check(board, board.side_to_move))
            keys.append(board.position_key())
        return _ReplayedGame(
            board=board,
            start_fen=start_fen,
            move_history=history,
            move_notes=notes,
            game_note=record.game_note,
            position_keys=keys,
            move_sides=sides,
            move_gave_check=checks,
        )

    def _commit_record(
        self,
        state: _ReplayedGame,
        *,
        game_id: str,
        name: str,
        created_at: str,
        saved_at: str,
    ) -> None:
        """Adopt a replayed record as the live game. `game_id` is the id the
        record lives under in the store — for an opened file that is the file
        name, not the `id` inside it, so the next save rewrites the file that
        was opened instead of a second one under the in-file id."""
        self.board = state.board
        self.start_fen = state.start_fen
        self.move_history = state.move_history
        self.move_notes = state.move_notes
        self.game_note = state.game_note
        self.position_keys = state.position_keys
        self.move_sides = state.move_sides
        self.move_gave_check = state.move_gave_check
        self.redo_stack = []
        self.redo_notes = []
        self.record_id = game_id
        self.record_name = name
        self.created_at = created_at
        self.saved_at = saved_at
        self.save_error = None  # the session now mirrors a file that just loaded
        self._cached_lines = None
        if self.engine.is_running():
            self.engine.new_game()

    def open_record(self, game_id: str) -> dict:
        """打开对局：load a saved game and replay it into this session.

        Deliberately does not write: opening a game must not bump its
        `updated_at` (the library sorts on it). The session adopts the id it
        was loaded BY, not the `id` the file carries: a hand-renamed file
        would otherwise write back to a different path on the next move and
        orphan the file just opened."""
        with self.lock:
            if self.store is None:
                raise StoreError("对局库未启用")
            record = self.store.load(game_id)
            state = self._replay_record(record)
            self._commit_record(
                state,
                game_id=game_id,
                name=record.name,
                created_at=record.created_at,
                saved_at=record.updated_at,
            )
            return self.position_payload()

    def import_record(self, record: GameRecord) -> dict:
        """Import a replay file, re-validating it first: the HTTP layer may
        hand over a pydantic model that never ran through `GameRecord.parse`,
        and only `parse` checks the note count against the move count. Saves
        the imported line as a new library entry, keeping the file's id when
        free and minting one when the library already uses it.

        The store write happens before the session commits: a failed write
        must leave the game the player is looking at untouched, not swap it
        for an import that never landed."""
        with self.lock:
            if self.store is None:
                raise StoreError("对局库未启用")
            record = GameRecord.parse(record.model_dump())
            # Pure: the whole line replays (or raises) before anything moves.
            state = self._replay_record(record)
            game_id = record.id
            try:
                taken = self.store.exists(game_id)
            except StoreError:
                # An id the store cannot even ask about (a foreign file with
                # "id": "我的对局") is not free either — mint a fresh one
                # rather than failing the import of otherwise valid content.
                taken = True
            if taken:
                game_id = self.store.new_id()
            saved = self.store.save(record.model_copy(update={"id": game_id}))
            self._commit_record(
                state,
                game_id=game_id,
                name=record.name,
                created_at=record.created_at,
                saved_at=saved.updated_at,
            )
            return self.position_payload()

    def _line_plies(self) -> list[dict]:
        """One entry per ply of the applied line, each carrying the position
        AFTER that ply — the same convention as the move result, so a game
        opened off disk can render ply by ply. Pure board work: no engine, no
        session state written."""
        chinese = self._history_chinese()
        board = Board.from_fen(self.start_fen)
        plies = []
        for i, uci in enumerate(self.move_history):
            board.apply_move(Move.from_uci(uci))
            plies.append({
                "move_uci": uci,
                "move_chinese": chinese[i] if i < len(chinese) else None,
                "fen": board.to_fen(),
                "side_to_move": board.side_to_move,
            })
        return plies

    def save_as(self, name: str) -> dict:
        """另存为：copy the current line into a fresh library entry, leaving
        the original file alone. This session switches to the new record."""
        with self.lock:
            if not self.move_history:
                raise IllegalMoveError("还没有走子，无法另存为")
            self.record_id = None
            self.created_at = None
            self.saved_at = None
            self.record_name = name
            self._persist()
            return self.position_payload()

    def sync_renamed_record(self, game_id: str, name: str) -> None:
        """Keep the open game's name in step when the library renames it. The
        store owns the write; renaming a game that is not open must not touch
        this session."""
        with self.lock:
            if self.record_id == game_id:
                self.record_name = name

    # ---------- navigation ----------

    def _undo_one(self) -> None:
        if not self.move_history:
            raise IllegalMoveError("没有可悔的棋步")
        self.board.undo_move()
        self.redo_stack.append(self.move_history.pop())
        self.redo_notes.append(self.move_notes.pop())
        self.position_keys.pop()
        self.move_sides.pop()
        self.move_gave_check.pop()
        self._cached_lines = None

    def _redo_one(self) -> None:
        if not self.redo_stack:
            raise IllegalMoveError("没有可重做的棋步")
        uci = self.redo_stack.pop()
        note = self.redo_notes.pop()
        mover = self.board.side_to_move
        self.board.apply_move(Move.from_uci(uci))
        self.move_history.append(uci)
        self.move_notes.append(note)
        self._record_ply(mover)

    def _record_ply(self, mover: str) -> None:
        self.position_keys.append(self.board.position_key())
        self.move_sides.append(mover)
        self.move_gave_check.append(is_in_check(self.board, self.board.side_to_move))
        self._cached_lines = None

    def undo(self, plies: int = 1) -> dict:
        """悔棋：回退指定步数（默认一步）。"""
        with self.lock:
            if plies < 1:
                raise IllegalMoveError(f"无效的步数：{plies}")
            if plies > len(self.move_history):
                raise IllegalMoveError("没有这么多可悔的棋步")
            for _ in range(plies):
                self._undo_one()
            self._persist()
            return self.position_payload()

    def redo(self, plies: int = 1) -> dict:
        """重做：恢复被悔掉的棋步。"""
        with self.lock:
            if plies < 1:
                raise IllegalMoveError(f"无效的步数：{plies}")
            if plies > len(self.redo_stack):
                raise IllegalMoveError("没有这么多可重做的棋步")
            for _ in range(plies):
                self._redo_one()
            self._persist()
            return self.position_payload()

    def goto(self, ply: int) -> dict:
        """跳转到走子历史中的第 ply 步（0 = 起始局面）。"""
        with self.lock:
            total = len(self.move_history) + len(self.redo_stack)
            if ply < 0 or ply > total:
                raise IllegalMoveError(f"无效的步数：{ply}")
            while len(self.move_history) > ply:
                self._undo_one()
            while len(self.move_history) < ply:
                self._redo_one()
            self._persist()
            return self.position_payload()

    # ---------- moves ----------

    def make_move(self, from_sq: str, to_sq: str) -> dict:
        with self.lock:
            move = Move.from_uci(from_sq + to_sq)
            legal_move = find_legal_move(self.board, move)
            if legal_move is None:
                raise IllegalMoveError(f"不合规则的走法：{from_sq}{to_sq}")
            return self._play_move(legal_move)

    def engine_move(self) -> dict:
        """Let the engine pick and play the best move for the side to move."""
        with self.lock:
            lines = self.current_lines()
            if not lines or not lines[0].best_move:
                raise IllegalMoveError("引擎没有可走的着法（本局可能已经结束）")
            move = Move.from_uci(lines[0].best_move)
            legal_move = find_legal_move(self.board, move)
            if legal_move is None:
                raise IllegalMoveError(f"引擎给出了不合规则的走法：{lines[0].best_move}")
            return self._play_move(legal_move, lines_before=lines)

    def _candidates(
        self, board_before: Board, lines: list[PvLine], played_uci: str
    ) -> list[dict]:
        """Top engine choices for the position before the move, in Chinese."""
        out = []
        for line in lines:
            if not line.best_move:
                continue
            pv = line.pv[:PV_PLIES]
            out.append({
                "rank": line.multipv,
                "move_uci": line.best_move,
                "move_chinese": _safe_notation(board_before, line.best_move),
                "score_cp": line.score_cp,
                "score_mate": line.score_mate,
                "pv_uci": pv,
                "pv_chinese": moves_to_chinese(board_before, pv),
                "is_played": line.best_move == played_uci,
            })
        return out

    def _passing_plan_from(self, board: Board, mover: str) -> dict | None:
        """Up to PASSING_PLAN_STEPS moves `mover` could play in a row if the
        opponent kept passing — the engine's answers on chained side-flipped
        ("null move") positions. Display-only; the calls go to the engine
        directly so the analysis cache is never touched. Returns None when the
        opponent is already in check (passing out of check is not a legal
        hypothetical, and Pikafish exits on that position), and stops the
        chain after a move that gives check."""
        opponent = other_side(mover)
        if is_in_check(board, opponent):
            return None
        scratch = board.clone()
        ucis: list[str] = []
        while len(ucis) < PASSING_PLAN_STEPS:
            if not self.engine.is_running():
                break
            null_board = scratch.clone()
            null_board.side_to_move = mover
            lines = self.engine.analyze(null_board.to_fen(), depth=DEPTH, multipv=1)
            if not lines or not lines[0].pv:
                break
            try:
                move = Move.from_uci(lines[0].pv[0])
            except (ValueError, IndexError):
                break
            if scratch.piece_at(move.from_sq) is None:
                break
            ucis.append(lines[0].pv[0])
            scratch.apply_move(move)
            if is_in_check(scratch, opponent):
                break
        if not ucis:
            return None
        chinese = moves_to_chinese(board, ucis)
        chinese += [None] * (len(ucis) - len(chinese))  # keep indices aligned
        return {"moves_uci": ucis, "moves_chinese": chinese}

    def _play_move(self, legal_move: Move, lines_before: list[PvLine] | None = None) -> dict:
        # A genuinely new move discards any undone continuation
        # (悔棋 -> 走新的一步 = 之前的分支被放弃) and the notes written on it.
        self.redo_stack = []
        self.redo_notes = []
        lines_before = lines_before if lines_before is not None else self.current_lines()
        best_cp_before = (
            score_to_cp(lines_before[0].score_cp, lines_before[0].score_mate) if lines_before else 0
        )
        best_move_uci = lines_before[0].best_move if lines_before else None
        played_uci = legal_move.to_uci()
        played_matches_best = best_move_uci == played_uci

        board_before = self.board.clone()
        move_history_before = list(self.move_history)
        mover = self.board.side_to_move

        self.board.apply_move(legal_move)
        self.move_history.append(played_uci)
        self.move_notes.append("")
        self._record_ply(mover)

        status = self.status_payload()
        terminal = status["status"] if status["status"] != "ongoing" else None

        # A move that ends the game cannot be a blunder: with no legal replies
        # the post-move search returns nothing, which used to be read as eval 0
        # and produced a ~99999 cp "loss" on a winning move.
        if terminal in ("checkmate", "stalemate"):
            cp_loss = 0
            classification = classify_cp_loss(0)
            lines_after: list[PvLine] = []
            # Decisive result, expressed from RED's perspective for the eval bar.
            eval_cp_red = (MATE_SCORE - 1) if mover == RED else -(MATE_SCORE - 1)
        else:
            lines_after = self.current_lines()
            opp_best_cp_after = (
                score_to_cp(lines_after[0].score_cp, lines_after[0].score_mate) if lines_after else 0
            )
            played_cp_after_movers_pov = -opp_best_cp_after
            cp_loss = cp_loss_for_move(best_cp_before, played_cp_after_movers_pov, played_matches_best)
            classification = classify_cp_loss(cp_loss)
            eval_cp_red = (
                to_red_perspective_cp(
                    lines_after[0].score_cp, lines_after[0].score_mate, self.board.side_to_move
                )
                if lines_after else None
            )

        # The opponent-passes probes analyse side-flipped positions; the real
        # engine exits on one where the move gives check, so each chain is
        # skipped there (see _passing_plan_from).
        passing_plan = (
            self._passing_plan_from(self.board, mover) if terminal is None else None
        )

        best_passing_plan = None
        if best_move_uci and not played_matches_best and classification.cp_loss > 0:
            best_board = _board_after(board_before, best_move_uci)
            if best_board is not None:
                best_passing_plan = self._passing_plan_from(best_board, mover)

        warning = repetition_warning(self.position_keys, self.move_sides, self.move_gave_check)
        explanation = build_explanation(
            board_before=board_before,
            move=legal_move,
            classification=classification,
            best_move_uci=best_move_uci,
            played_matches_best=played_matches_best,
            move_history_before=move_history_before,
            terminal_status=terminal,
            repetition_note=status.get("result_note") if terminal else warning,
        )

        opening_name = explanation["opening"].get("name")
        # The opening the move entered names a new record; a failed save lands
        # in `save_error` and never disturbs the result below.
        self._persist(default_name=opening_name)

        return {
            "fen": self.board.to_fen(),
            "side_to_move": self.board.side_to_move,
            "move_uci": played_uci,
            "move_chinese": explanation["move_chinese"],
            "played_matches_best": played_matches_best,
            "best_move_uci": best_move_uci,
            "best_move_chinese": explanation["best_move_chinese"],
            "label": classification.label,
            "label_en": classification.label_en,
            "color": classification.color,
            "cp_loss": classification.cp_loss,
            "eval_cp": eval_cp_red,
            "candidates": self._candidates(board_before, lines_before, played_uci),
            "why_better": explanation["why_better"],
            "intents": explanation["intents"],
            "intent_text": explanation["intent_text"],
            "lines": [_pv_out(line) for line in lines_after],
            "follow_up": None if terminal else _follow_up_out(self.board, lines_after),
            "passing_plan": passing_plan,
            "best_passing_plan": best_passing_plan,
            "explanation": explanation["text"],
            "tactics": explanation["tactics"],
            "opening_name": opening_name,
            "opening_note": explanation["opening"].get("note"),
            "in_book": bool(explanation["opening"].get("in_book")),
            "left_book_now": bool(explanation["opening"].get("left_book_now")),
            "game_status": status["status"],
            "result_note": status.get("result_note"),
            "in_check": status["in_check"],
            "winner": status["winner"],
            **self._record_fields(),
        }


def _follow_up_out(board: Board, lines: list[PvLine]) -> dict | None:
    if not lines or not lines[0].pv:
        return None
    pv = lines[0].pv[:FOLLOW_UP_PLIES]
    chinese = moves_to_chinese(board, pv)
    chinese += [None] * (len(pv) - len(chinese))  # keep indices aligned
    return {"moves_uci": pv, "moves_chinese": chinese}


def _board_after(board: Board, uci: str) -> Board | None:
    """A clone of `board` with `uci` applied, or None when it cannot be."""
    try:
        move = Move.from_uci(uci)
    except (ValueError, IndexError):
        return None
    if board.piece_at(move.from_sq) is None:
        return None
    clone = board.clone()
    clone.apply_move(move)
    return clone


def _safe_notation(board: Board, uci: str) -> str | None:
    try:
        move = Move.from_uci(uci)
    except (ValueError, IndexError):
        return None
    if board.piece_at(move.from_sq) is None:
        return None
    return move_to_chinese(board, move)


def _pv_out(line: PvLine) -> dict:
    return {
        "multipv": line.multipv,
        "score_cp": line.score_cp,
        "score_mate": line.score_mate,
        "pv": line.pv,
    }
