interface EvalBarProps {
  evalCp: number | null; // positive = red (bottom) is better; null = nobody analysed this position
  height?: number;
}

const CAP = 800; // cp value at which the bar is considered "maxed out"

export function EvalBar({ evalCp, height = 500 }: EvalBarProps) {
  // A position no analysis covers (a ply opened off disk, or a move played with
  // the engine down) has no evaluation. Falling back to 0 would render 0.00 and
  // a half-red bar — a dead-equal verdict the engine never gave — so the bar
  // shows a neutral strip and 「—」 instead.
  const known = evalCp !== null;
  const cp = evalCp ?? 0;
  const clamped = Math.max(-CAP, Math.min(CAP, cp));
  const redFraction = 0.5 + clamped / (CAP * 2);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <div
        style={{
          width: 28,
          height,
          borderRadius: 6,
          overflow: "hidden",
          border: "1px solid #444",
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          background: "#1a1a1a",
        }}
        title={known ? `评估：${cp > 0 ? "+" : ""}${(cp / 100).toFixed(2)}` : "评估：未分析"}
      >
        <div
          style={{
            height: height * redFraction,
            background: known ? "#c0392b" : "#5a5a5a",
            transition: "height 0.3s ease",
          }}
        />
      </div>
      <div style={{ fontSize: 13, fontFamily: "monospace", color: known ? "#333" : "#7a7a7a" }}>
        {known ? `${cp > 0 ? "+" : ""}${(cp / 100).toFixed(2)}` : "—"}
      </div>
    </div>
  );
}
