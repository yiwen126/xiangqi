import { useCallback, useState } from "react";
import { Board } from "./components/Board";
import { CandidatePanel } from "./components/CandidatePanel";
import { ConceptPanel } from "./components/ConceptPanel";
import { Controls } from "./components/Controls";
import { EvalBar } from "./components/EvalBar";
import { GameLibrary } from "./components/GameLibrary";
import { GameStatus } from "./components/GameStatus";
import { MoveList, type MoveEntry } from "./components/MoveList";
import { NotePanel } from "./components/NotePanel";
import { useBoardFit } from "./state/useBoardFit";
import { useGame } from "./state/useGame";

export default function App() {
  const g = useGame();
  const boardHeight = useBoardFit();

  const [libraryOpen, setLibraryOpen] = useState(false);
  /** A failure from the library modal. It stays here rather than in the hook
   * because only the modal can fail this way. */
  const [libraryError, setLibraryError] = useState<string | null>(null);

  const openLibrary = useCallback(() => {
    setLibraryError(null); // a fresh visit starts with a clean slate
    setLibraryOpen(true);
  }, []);
  const closeLibrary = useCallback(() => setLibraryOpen(false), []);

  const moveEntries: MoveEntry[] = g.moves.map((r, i) => {
    const note = g.notes[i] ?? "";
    return {
      ply: i + 1,
      side: g.otherSide(r.side_to_move),
      moveUci: r.move_uci,
      moveChinese: r.move_chinese,
      label: r.label,
      color: r.color,
      cpLoss: r.cp_loss,
      applied: i < g.pointer,
      hasNote: note.trim() !== "",
      note,
    };
  });

  const current = g.current;
  // 开局还没走子时 0 只是刻度的中点；走过但没人分析的局面必须显示「—」，
  // 否则评估条会给出一个看起来像「均势」的假数字。
  const evalCp = current ? current.eval_cp : 0;
  const lastMove = current
    ? { from: current.move_uci.slice(0, 2), to: current.move_uci.slice(2) }
    : null;
  const suggestedMove =
    current && !current.played_matches_best && current.best_move_uci
      ? { from: current.best_move_uci.slice(0, 2), to: current.best_move_uci.slice(2) }
      : null;

  const enginePaused = !g.autoPlayArmed && g.controlledBy[g.sideToMove] === "engine";

  // The mover is the side to move *after* the displayed ply (see api-contract).
  const currentMoveLabel = current
    ? `${g.otherSide(current.side_to_move) === "w" ? "红" : "黑"} ${
        current.move_chinese ?? current.move_uci
      }`
    : null;

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">象棋师父 · Xiangqi Shifu</h1>
        <p className="app__subtitle">走一步棋，引擎会告诉你这步棋好不好、以及更好的选择。</p>
      </header>

      {!g.engineReady && (
        <div className="banner banner--error">
          引擎不可用。请先运行 <code>scripts/setup_engine.sh</code> 下载 Pikafish，然后刷新页面。
        </div>
      )}
      {g.error && <div className="banner banner--warn">{g.error}</div>}
      {libraryError && <div className="banner banner--warn">{libraryError}</div>}

      <div className="layout">
        <div className="layout__board">
          <EvalBar evalCp={evalCp} height={boardHeight} />
          <Board
            fen={g.displayFen}
            flipped={g.flipped}
            lastMove={lastMove}
            suggestedMove={suggestedMove}
            onMove={g.playMove}
            disabled={!g.humanCanMove || g.busy}
            height={boardHeight}
          />
        </div>

        <div className="layout__teach">
          <div className="layout__scroll">
            <ConceptPanel move={current} />
            <NotePanel
              ply={g.viewPly}
              moveLabel={currentMoveLabel}
              notes={g.notes}
              gameNote={g.gameNote}
              savedAt={g.savedAt}
              saving={g.noteSaving}
              onSave={g.setNote}
              onJump={g.viewPlyAt}
            />
            <CandidatePanel candidates={current?.candidates ?? []} />
          </div>
        </div>

        <div className="layout__side">
          <Controls
            controlledBy={g.controlledBy}
            onControlChange={g.setController}
            onNewGame={() => void g.startNewGame()}
            onFlip={g.toggleFlip}
            onUndo={() => void g.undo()}
            onRedo={() => void g.redo()}
            onEngineMove={() => void g.engineMove()}
            canUndo={g.canUndo}
            canRedo={g.canRedo}
            canEngineMove={g.gameStatus === "ongoing" && g.engineReady && g.isViewingLive}
            sideToMove={g.sideToMove}
            busy={g.busy}
            gameName={g.gameName}
            savedAt={g.savedAt}
            saveError={g.saveError}
            onOpenLibrary={openLibrary}
          />

          <GameStatus
            status={g.gameStatus}
            winner={g.winner}
            inCheck={g.inCheck}
            sideToMove={g.sideToMove}
            resultNote={g.resultNote}
            isViewingLive={g.isViewingLive}
            viewPly={g.viewPly}
            onReturnToLive={() => g.viewPlyAt(g.pointer)}
            enginePaused={enginePaused}
          />

          <MoveList
            moves={moveEntries}
            currentPly={g.viewPly > 0 ? g.viewPly : null}
            onSelect={g.viewPlyAt}
          />
        </div>
      </div>

      {/* An overlay, so it costs the one-screen layout nothing. */}
      <GameLibrary
        open={libraryOpen}
        currentId={g.gameId}
        busy={g.busy}
        onClose={closeLibrary}
        onOpen={g.openGame}
        onImport={g.importRecord}
        onSaveAs={g.saveAs}
        onError={setLibraryError}
        onRenamed={(id, name) => {
          if (id === g.gameId) g.adoptGameName(name); // the open game was renamed
        }}
      />
    </div>
  );
}
