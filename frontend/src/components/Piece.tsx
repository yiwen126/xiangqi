import { PIECE_LABELS, isRed } from "../board/fen";

interface PieceProps {
  piece: string;
  x: number;
  y: number;
  r: number;
  selected?: boolean;
  onClick?: () => void;
}

export function Piece({ piece, x, y, r, selected, onClick }: PieceProps) {
  const red = isRed(piece);
  return (
    <g onClick={onClick} style={{ cursor: onClick ? "pointer" : "default" }}>
      {selected && (
        <circle cx={x} cy={y} r={r + 5} fill="none" stroke="#3aa1ff" strokeWidth={3} />
      )}
      <circle
        cx={x}
        cy={y}
        r={r}
        fill="#f2e6ce"
        stroke={red ? "#b3261e" : "#1a1a1a"}
        strokeWidth={2.5}
      />
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={r * 1.05}
        fontWeight={700}
        fill={red ? "#b3261e" : "#1a1a1a"}
        style={{ userSelect: "none" }}
      >
        {PIECE_LABELS[piece] ?? piece}
      </text>
    </g>
  );
}
