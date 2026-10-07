import { useEffect, useRef } from "react";
import type { Side } from "../api/types";

export interface MoveEntry {
  ply: number;
  side: Side;
  moveUci: string;
  moveChinese: string | null;
  label: string;
  color: string;
  cpLoss: number;
  /** Whether this move is currently applied to the live board (vs. undone). */
  applied: boolean;
  /** Whether this ply carries a note — the ✎ marker. */
  hasNote: boolean;
  /** The note itself, shown in the row's tooltip. */
  note: string;
}

interface MoveListProps {
  moves: MoveEntry[];
  /** ply of the move that produced the currently-displayed position, or null at the start. */
  currentPly: number | null;
  onSelect: (ply: number) => void;
}

export function MoveList({ moves, currentPly, onSelect }: MoveListProps) {
  const currentRow = useRef<HTMLDivElement | null>(null);

  // Keep the move being viewed in sight — after a new move that means the
  // newest row, so a long game never needs scrolling to see where you are.
  // `nearest` scrolls only when the row is actually out of view, so it does
  // not yank the list around while the current row is already visible.
  useEffect(() => {
    currentRow.current?.scrollIntoView({ block: "nearest" });
  }, [currentPly, moves.length]);

  return (
    <div className="movelist">
      {moves.length === 0 && <div className="movelist__empty">还没有走子</div>}
      {moves.map((m) => (
        <div
          key={m.ply}
          ref={currentPly === m.ply ? currentRow : undefined}
          onClick={() => onSelect(m.ply)}
          title={m.note ? `${m.note}\n点击查看这一步的局面和讲解` : "点击查看这一步的局面和讲解"}
          className={[
            "movelist__row",
            currentPly === m.ply ? "movelist__row--current" : "",
            m.applied ? "" : "movelist__row--undone",
          ].filter(Boolean).join(" ")}
        >
          <span className="movelist__ply">{m.ply}.</span>
          <span className={`movelist__side movelist__side--${m.side}`}>
            {m.side === "w" ? "红" : "黑"}
          </span>
          <span className="movelist__cn">
            {m.moveChinese ?? m.moveUci}{" "}
            <span className="movelist__uci">{m.moveUci}</span>
          </span>
          {m.hasNote && <span className="movelist__note" aria-hidden="true">✎</span>}
          <span className="badge" style={{ background: m.color }}>{m.label}</span>
        </div>
      ))}
    </div>
  );
}
