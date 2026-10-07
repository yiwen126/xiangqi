import type { Side } from "../api/types";
import type { Controller } from "../state/useGame";

interface ControlsProps {
  controlledBy: Record<Side, Controller>;
  onControlChange: (side: Side, mode: Controller) => void;
  onNewGame: () => void;
  onFlip: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onEngineMove: () => void;
  canUndo: boolean;
  canRedo: boolean;
  canEngineMove: boolean;
  sideToMove: Side;
  busy: boolean;
  /** The open game's 对局库 name; null until the first move creates the record. */
  gameName: string | null;
  /** When the record was last written; null means nothing is saved yet. */
  savedAt: string | null;
  /** Non-null when the last auto-save failed (the page banner has the detail). */
  saveError: string | null;
  onOpenLibrary: () => void;
}

export function Controls({
  controlledBy,
  onControlChange,
  onNewGame,
  onFlip,
  onUndo,
  onRedo,
  onEngineMove,
  canUndo,
  canRedo,
  canEngineMove,
  sideToMove,
  busy,
  gameName,
  savedAt,
  saveError,
  onOpenLibrary,
}: ControlsProps) {
  // 保存失败 must never look like 已保存: the failure wins over a stale savedAt.
  const saveState = saveError ? "保存失败" : savedAt ? "已保存" : "未保存";

  return (
    <div className="card">
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="game__head">
          <span
            className="game__name"
            title={gameName ?? "走出第一步棋，这盘棋就会自动保存到对局库"}
          >
            {gameName ?? "新对局"}
          </span>
          <span
            className={saveError ? "game__save game__save--error" : "game__save"}
            title={saveError ?? undefined}
          >
            {saveState}
          </span>
        </div>
        {/* Three buttons wrap to two lines in the narrow column rather than
            squeezing 翻转棋盘 down to a broken label. */}
        <div className="btn-row btn-row--wrap">
          <button className="btn" onClick={onNewGame} disabled={busy}>新对局</button>
          <button
            className="btn"
            onClick={onOpenLibrary}
            title="对局库：回看、改名、导出、导入已保存的棋"
          >
            对局库
          </button>
          <button className="btn" onClick={onFlip}>翻转棋盘</button>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={onUndo} disabled={busy || !canUndo} title="悔棋：退回到你自己的一步">
            ↩ 悔棋
          </button>
          <button className="btn" onClick={onRedo} disabled={busy || !canRedo} title="重做：恢复被悔掉的一步">
            ↪ 重做
          </button>
        </div>
        <button
          className="btn btn--primary"
          onClick={onEngineMove}
          disabled={busy || !canEngineMove}
          title="让引擎替当前一方走出它认为最好的一步"
        >
          ★ 试最佳走法（{sideToMove === "w" ? "红" : "黑"}）
        </button>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 2 }}>
          {(["w", "b"] as Side[]).map((side) => (
            <label key={side} className="control-row">
              <span style={{ width: 32 }}>{side === "w" ? "红方" : "黑方"}</span>
              <select
                value={controlledBy[side]}
                onChange={(e) => onControlChange(side, e.target.value as Controller)}
              >
                <option value="human">我来走</option>
                <option value="engine">引擎</option>
              </select>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
