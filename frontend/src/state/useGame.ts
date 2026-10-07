import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  GameRecord,
  GameStatus,
  LoadedGameResponse,
  MoveResultResponse,
  PlyEntry,
  PlyView,
  Side,
} from "../api/types";
import { START_FEN } from "../board/constants";

export type Controller = "human" | "engine";

function otherSide(s: Side): Side {
  return s === "w" ? "b" : "w";
}

/** The moves played this game, plus where the live board and the viewer sit.
 *
 * `moves` is the full cached timeline including plies currently undone. A ply
 * from an opened game is a placeholder (`loaded_only`) whose engine fields are
 * inert, but it carries its own board, so the move list, history browsing and
 * 悔棋 work through this one model instead of a second code path.
 * `notes` is one entry per ply, exactly parallel to `moves`: a note travels
 * with its ply through undo and redo, and dies with an undone branch that a
 * new move discards.
 * `pointer` is how many are applied to the live backend board.
 * `viewPly` is which ply the UI is *displaying* — it moves independently so
 * that browsing history never touches the backend (and so can never trigger
 * the engine's auto-move). All of these live in one state object so updates
 * are atomic and the updater stays pure.
 */
interface Timeline {
  moves: PlyEntry[];
  notes: string[];
  pointer: number;
  viewPly: number;
}

const EMPTY: Timeline = { moves: [], notes: [], pointer: 0, viewPly: 0 };

/** The session status and record identity every response shares. `game_note`
 * is optional because `MoveResultResponse` does not carry it — a played move
 * never changes the whole-game note. */
interface StatusPayload {
  side_to_move: Side;
  game_status: GameStatus;
  winner: Side | null;
  in_check: boolean;
  result_note: string | null;
  game_id: string | null;
  game_name: string | null;
  saved_at: string | null;
  save_error: string | null;
  game_note?: string;
}

/** One ply of a game opened off disk, shaped as a `PlyEntry`.
 *
 * Every engine-derived field is inert rather than guessed: a label or an eval
 * manufactured here would be a lie the UI then displays as analysis. Task 9
 * renders a hint for `loaded_only` entries instead of an empty 讲解 card.
 */
function loadedEntry(res: LoadedGameResponse, ply: PlyView): PlyEntry {
  return {
    fen: ply.fen,
    side_to_move: ply.side_to_move,
    move_uci: ply.move_uci,
    move_chinese: ply.move_chinese,
    played_matches_best: false,
    best_move_uci: null,
    best_move_chinese: null,
    label: "—",
    label_en: "none",
    color: "#cfcabb",
    cp_loss: 0,
    eval_cp: null,
    candidates: [],
    why_better: null,
    intent_text: null,
    intents: [],
    follow_up: null,
    passing_plan: null,
    best_passing_plan: null,
    explanation: "",
    tactics: [],
    opening_name: null,
    opening_note: null,
    in_book: false,
    left_book_now: false,
    game_status: "ongoing",
    result_note: null,
    in_check: false,
    winner: null,
    // The line belongs to this record; only the auto-save outcome is
    // per-move, and a loaded ply was not saved by this session.
    game_id: res.game_id,
    game_name: res.game_name,
    saved_at: res.saved_at,
    save_error: null,
    loaded_only: true,
  };
}

export function useGame() {
  const [timeline, setTimeline] = useState<Timeline>(EMPTY);
  const [sideToMove, setSideToMove] = useState<Side>("w");
  const [gameStatus, setGameStatus] = useState<GameStatus>("ongoing");
  const [winner, setWinner] = useState<Side | null>(null);
  const [inCheck, setInCheck] = useState(false);
  const [resultNote, setResultNote] = useState<string | null>(null);
  const [flipped, setFlipped] = useState(false);
  const [controlledBy, setControlledBy] = useState<Record<Side, Controller>>({
    w: "human",
    b: "human",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [engineReady, setEngineReady] = useState(true);

  // 对局库 identity and the note on the game as a whole. The per-ply notes
  // live in the timeline, next to the moves they travel with.
  const [gameNote, setGameNote] = useState("");
  const [gameId, setGameId] = useState<string | null>(null);
  const [gameName, setGameName] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [noteSaving, setNoteSaving] = useState(false);
  /** Non-null while the last auto-save failed. The message itself goes onto
   * `error` (the player already watches that banner), but Controls needs to
   * tell 保存失败 apart from a stale 已保存. */
  const [saveError, setSaveError] = useState<string | null>(null);

  /** Orders note-write responses: a debounced save can land after a newer one
   * and would otherwise revert `notes` to an older line. */
  const noteSeq = useRef(0);

  /** Drop any in-flight note write: its response is aligned to a line that no
   * longer exists here, so applying it would put notes on the wrong plies (or
   * leak a note from one game into another). */
  const abandonNoteWrites = useCallback(() => {
    noteSeq.current += 1;
    setNoteSaving(false);
  }, []);

  /** Whether the engine is allowed to move on its own right now.
   *
   * This is the fix for 悔棋 being unusable in engine games: previously the
   * auto-move effect re-fired whenever `busy` flipped false, so undoing a ply
   * simply handed the turn back to the engine, which instantly replayed the
   * move that was just taken back. Auto-play is now explicit state — disarmed
   * by 悔棋/重做 (the user is navigating, not playing) and re-armed only by a
   * deliberate act: playing a move, asking the engine to move, or a new game.
   */
  const [autoPlayArmed, setAutoPlayArmed] = useState(true);

  const applyStatus = useCallback((s: StatusPayload) => {
    setSideToMove(s.side_to_move);
    setGameStatus(s.game_status);
    setWinner(s.winner);
    setInCheck(s.in_check);
    setResultNote(s.result_note);
    setGameId(s.game_id);
    setGameName(s.game_name);
    setSavedAt(s.saved_at);
    // A failed auto-save must never look like 已保存: it goes onto the same
    // error channel the player already sees for a failed move. A successful
    // response does not clear an older error — the next action does.
    setSaveError(s.save_error);
    if (s.save_error) setError(s.save_error);
    if (s.game_note !== undefined) setGameNote(s.game_note);
  }, []);

  const startNewGame = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const pos = await api.newGame();
      applyStatus(pos);
      setTimeline(EMPTY);
      abandonNoteWrites(); // a note echo from the old game must not land in this one
      setAutoPlayArmed(true);
      setEngineReady(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setEngineReady(false);
    } finally {
      setBusy(false);
    }
  }, [applyStatus, abandonNoteWrites]);

  useEffect(() => {
    void startNewGame();
  }, [startNewGame]);

  const recordResult = useCallback(
    (result: MoveResultResponse) => {
      applyStatus(result);
      // Pure updater: a genuinely new move discards any undone continuation —
      // and the notes that travelled with it.
      setTimeline((t) => {
        const moves = [...t.moves.slice(0, t.pointer), result];
        const notes = [...t.notes.slice(0, t.pointer), ""];
        return { moves, notes, pointer: moves.length, viewPly: moves.length };
      });
    },
    [applyStatus],
  );

  const playMove = useCallback(
    async (from: string, to: string) => {
      if (busy || gameStatus !== "ongoing") return;
      setBusy(true);
      setError(null);
      try {
        const result = await api.makeMove(from, to);
        recordResult(result);
        setAutoPlayArmed(true); // a human move resumes normal play
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [busy, gameStatus, recordResult],
  );

  const engineMove = useCallback(async () => {
    if (busy || gameStatus !== "ongoing") return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.engineMove();
      recordResult(result);
      setAutoPlayArmed(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [busy, gameStatus, recordResult]);

  /** Side to move once the live board sits at `ply` plies. */
  const sideAt = useCallback(
    (ply: number): Side => (ply === 0 ? "w" : timeline.moves[ply - 1].side_to_move),
    [timeline.moves],
  );

  /** How many plies to step so the user lands on a turn they actually control.
   * In an engine game a single 悔棋 lands on the engine's turn, so step 2. */
  const stepToHumanTurn = useCallback(
    (targetPly: (n: number) => number, limit: number): number => {
      for (let n = 1; n <= Math.min(2, limit); n++) {
        if (controlledBy[sideAt(targetPly(n))] === "human") return n;
      }
      return Math.min(1, limit);
    },
    [controlledBy, sideAt],
  );

  const undo = useCallback(async () => {
    if (busy || timeline.pointer === 0) return;
    const plies = stepToHumanTurn((n) => timeline.pointer - n, timeline.pointer);
    if (plies === 0) return;
    setBusy(true);
    setError(null);
    setAutoPlayArmed(false); // never let the engine replay what was just undone
    try {
      const pos = await api.undo(plies);
      applyStatus(pos);
      setTimeline((t) => {
        const pointer = pos.move_history.length;
        // The response's notes cover the whole line, redo branch included, so
        // they stay parallel to `moves`; taking them also re-syncs a note that
        // arrived while the line was changing.
        return { ...t, notes: pos.notes, pointer, viewPly: pointer };
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [busy, timeline.pointer, stepToHumanTurn, applyStatus]);

  const redo = useCallback(async () => {
    const available = timeline.moves.length - timeline.pointer;
    if (busy || available <= 0) return;
    const plies = stepToHumanTurn((n) => timeline.pointer + n, available);
    if (plies === 0) return;
    setBusy(true);
    setError(null);
    setAutoPlayArmed(false); // stay disarmed while stepping through history
    try {
      const pos = await api.redo(plies);
      applyStatus(pos);
      setTimeline((t) => {
        const pointer = pos.move_history.length;
        // As in undo: the whole line's notes ride back with the replayed plies.
        return { ...t, notes: pos.notes, pointer, viewPly: pointer };
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [busy, timeline.moves.length, timeline.pointer, stepToHumanTurn, applyStatus]);

  /** 写笔记. `ply` is 1-based over the whole line (redo branch included);
   * `null` writes the whole-game note. The response is the whole note line,
   * so it replaces `notes` wholesale rather than patching one slot. */
  const setNote = useCallback(async (ply: number | null, text: string) => {
    const seq = ++noteSeq.current;
    setNoteSaving(true);
    setError(null);
    try {
      const res = await api.setNote(ply, text);
      if (seq !== noteSeq.current) return; // a newer write already answered
      setTimeline((t) =>
        // A response aligned to another line (a move or 悔棋 landed while the
        // write was in flight) must not shift notes onto the wrong plies; the
        // next position response re-syncs it.
        res.notes.length === t.moves.length ? { ...t, notes: res.notes } : t,
      );
      setGameNote(res.game_note);
      setSavedAt(res.saved_at);
      // A failed note write must never look like 已保存.
      setSaveError(res.save_error);
      if (res.save_error) setError(res.save_error);
    } catch (e) {
      if (seq === noteSeq.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (seq === noteSeq.current) setNoteSaving(false);
    }
  }, []);

  /** Replace the session with a record loaded from the library (打开/导入).
   *
   * The line and every board come from `plies`, so the move list, history
   * browsing and 悔棋 keep working through the one `Timeline` model. */
  const applyLoaded = useCallback(
    (res: LoadedGameResponse) => {
      applyStatus(res);
      setTimeline({
        moves: res.plies.map((ply) => loadedEntry(res, ply)),
        notes: res.notes,
        pointer: res.plies.length,
        viewPly: res.plies.length,
      });
      // Looking at a record is not playing it: an armed auto-play would make
      // the engine move in the game just opened and auto-save that move into
      // the record the player only wanted to look at. 已暂停 already has UI,
      // and playing a move re-arms it.
      setAutoPlayArmed(false);
      abandonNoteWrites();
    },
    [applyStatus, abandonNoteWrites],
  );

  /** 打开对局. Returns null on success, else the message it also put on
   * `error` — the 对局库 modal stays open on a 404/400 and shows it in place,
   * instead of closing over a failure the player never sees. */
  const openGame = useCallback(
    async (id: string): Promise<string | null> => {
      // Opening replaces the whole line; racing an in-flight move or engine
      // reply would land its result in the newly opened game.
      if (busy) return "正在处理上一步，请稍候。";
      setBusy(true);
      setError(null);
      try {
        applyLoaded(await api.openGame(id));
        return null;
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message);
        return message;
      } finally {
        setBusy(false);
      }
    },
    [busy, applyLoaded],
  );

  /** 导入复盘. Same contract as `openGame`: null on success, message otherwise. */
  const importRecord = useCallback(
    async (record: GameRecord): Promise<string | null> => {
      if (busy) return "正在处理上一步，请稍候。";
      setBusy(true);
      setError(null);
      try {
        applyLoaded(await api.importGame(record));
        return null;
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message);
        return message;
      } finally {
        setBusy(false);
      }
    },
    [busy, applyLoaded],
  );

  /** 另存为：the line and its notes do not move, only the identity does.
   * Same contract as `openGame`. */
  const saveAs = useCallback(
    async (name: string): Promise<string | null> => {
      if (busy) return "正在处理上一步，请稍候。";
      setBusy(true);
      setError(null);
      try {
        applyStatus(await api.saveAs(name));
        return null;
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message);
        return message;
      } finally {
        setBusy(false);
      }
    },
    [busy, applyStatus],
  );

  /** Adopt a name given to the open game elsewhere: the 对局库 modal renames
   * files straight through the client, so the session would otherwise show the
   * old name until the next status response. */
  const adoptGameName = useCallback((name: string) => setGameName(name), []);

  /** Pure client-side view navigation — never touches the backend. */
  const viewPlyAt = useCallback((ply: number) => {
    setTimeline((t) => ({ ...t, viewPly: ply }));
  }, []);

  const setController = useCallback((side: Side, mode: Controller) => {
    setControlledBy((c) => ({ ...c, [side]: mode }));
    setAutoPlayArmed(true); // an explicit control change is a deliberate act
  }, []);

  const shouldEngineMove =
    gameStatus === "ongoing" &&
    engineReady &&
    autoPlayArmed &&
    !busy &&
    controlledBy[sideToMove] === "engine";

  useEffect(() => {
    if (!shouldEngineMove) return;
    const t = setTimeout(() => void engineMove(), 400);
    return () => clearTimeout(t);
  }, [shouldEngineMove, engineMove]);

  const { moves, pointer, viewPly, notes } = timeline;
  const current = viewPly > 0 ? moves[viewPly - 1] : null;

  return {
    // position / status
    sideToMove,
    gameStatus,
    winner,
    inCheck,
    resultNote,
    displayFen: current ? current.fen : START_FEN,
    current,
    // timeline
    moves,
    notes,
    pointer,
    viewPly,
    isViewingLive: viewPly === pointer,
    // 对局库 record and notes
    gameNote,
    gameId,
    gameName,
    savedAt,
    saveError,
    noteSaving,
    otherSide,
    // flags
    flipped,
    busy,
    error,
    engineReady,
    controlledBy,
    autoPlayArmed,
    canUndo: pointer > 0,
    canRedo: pointer < moves.length,
    humanCanMove:
      viewPly === pointer && controlledBy[sideToMove] === "human" && gameStatus === "ongoing",
    // actions
    startNewGame,
    playMove,
    engineMove,
    undo,
    redo,
    viewPlyAt,
    setController,
    setNote,
    openGame,
    importRecord,
    saveAs,
    adoptGameName,
    toggleFlip: () => setFlipped((f) => !f),
  };
}
