import type { GameStatus as Status, Side } from "../api/types";

interface GameStatusProps {
  status: Status;
  winner: Side | null;
  inCheck: boolean;
  sideToMove: Side;
  resultNote: string | null;
  isViewingLive: boolean;
  viewPly: number;
  onReturnToLive: () => void;
  /** True when the engine controls the side to move but is deliberately paused
   * (after 悔棋/重做), so the user knows why nothing is happening. */
  enginePaused: boolean;
}

const SIDE_CN: Record<Side, string> = { w: "红方", b: "黑方" };

function headline(status: Status, winner: Side | null): string | null {
  switch (status) {
    case "checkmate":
      return `将死！${winner ? SIDE_CN[winner] : ""}获胜。`;
    case "stalemate":
      return `困毙！${winner ? SIDE_CN[winner] : ""}获胜。`;
    case "draw_repetition":
      return "和棋（重复局面）。";
    case "perpetual_loss":
      return `长将判负${winner ? `，${SIDE_CN[winner]}获胜` : ""}。`;
    default:
      return null;
  }
}

export function GameStatus({
  status,
  winner,
  inCheck,
  sideToMove,
  resultNote,
  isViewingLive,
  viewPly,
  onReturnToLive,
  enginePaused,
}: GameStatusProps) {
  const title = headline(status, winner);

  return (
    <div className="card status">
      {title ? (
        <>
          <div className="status__result">{title}</div>
          {resultNote && <div className="status__note">{resultNote}</div>}
        </>
      ) : (
        <div>
          轮到{SIDE_CN[sideToMove]}
          {inCheck ? "（将军！）" : ""}
        </div>
      )}

      {enginePaused && status === "ongoing" && (
        <div className="status__paused">
          引擎已暂停（悔棋后）。走一步棋，或点「试最佳走法」继续。
        </div>
      )}

      {!isViewingLive && (
        <div className="status__browsing">
          正在查看{viewPly === 0 ? "开局" : `第 ${viewPly} 步`}的历史局面 ·{" "}
          <span className="status__link" onClick={onReturnToLive}>返回当前对局</span>
        </div>
      )}
    </div>
  );
}
