import { useState } from "react";
import type { Grid } from "../board/fen";
import { parseFen, squareName, squareToRC } from "../board/fen";
import { BLACK_FILE_NUMERALS, RED_FILE_NUMERALS } from "../board/constants";
import { Piece } from "./Piece";

const CELL = 58;
// MARGIN holds the 中文记谱 numerals. It must clear the back-rank pieces
// (radius CELL * 0.42 ≈ 24px) or the numerals render underneath them.
const MARGIN = 46;
const PAD = 22; // outer gutter holding the a-i / 0-9 coordinate labels
// Clears the piece radius (24) plus half the numeral's own text box, so the
// glyph never collides with a back-rank piece.
const NUMERAL_OFFSET = 35;
const COLS = 9;
const ROWS = 10;
const GRID_W = (COLS - 1) * CELL;
const GRID_H = (ROWS - 1) * CELL;
const WIDTH = PAD * 2 + MARGIN * 2 + GRID_W;
export const BOARD_HEIGHT = PAD * 2 + MARGIN * 2 + GRID_H;
const HEIGHT = BOARD_HEIGHT;
/** Intrinsic aspect ratio, so callers can fit the board to a viewport. */
export const BOARD_ASPECT = WIDTH / HEIGHT;

interface BoardProps {
  fen: string;
  flipped: boolean;
  lastMove?: { from: string; to: string } | null;
  suggestedMove?: { from: string; to: string } | null;
  onMove: (from: string, to: string) => void;
  disabled?: boolean;
  /** Rendered height in px. The viewBox is fixed, so this just scales the SVG. */
  height?: number;
}

function pointToPixel(row: number, col: number, flipped: boolean) {
  const r = flipped ? ROWS - 1 - row : row;
  const c = flipped ? COLS - 1 - col : col;
  return { x: PAD + MARGIN + c * CELL, y: PAD + MARGIN + r * CELL };
}

export function Board({ fen, flipped, lastMove, suggestedMove, onMove, disabled, height }: BoardProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const grid: Grid = parseFen(fen);

  function handleSquareClick(square: string) {
    if (disabled) return;
    const [row, col] = squareToRC(square);
    const piece = grid[row][col];
    if (selected === square) {
      setSelected(null);
      return;
    }
    if (selected) {
      onMove(selected, square);
      setSelected(null);
      return;
    }
    if (piece) setSelected(square);
  }

  const vLines = [];
  for (let c = 0; c < COLS; c++) {
    const top = pointToPixel(0, c, flipped);
    const bottom = pointToPixel(9, c, flipped);
    const isEdge = c === 0 || c === COLS - 1;
    if (isEdge) {
      vLines.push(<line key={`v${c}`} x1={top.x} y1={top.y} x2={bottom.x} y2={bottom.y} stroke="#5a4632" strokeWidth={1.5} />);
    } else {
      const midTop = pointToPixel(4, c, flipped);
      const midBottom = pointToPixel(5, c, flipped);
      vLines.push(
        <line key={`v${c}a`} x1={top.x} y1={top.y} x2={midTop.x} y2={midTop.y} stroke="#5a4632" strokeWidth={1.5} />,
        <line key={`v${c}b`} x1={midBottom.x} y1={midBottom.y} x2={bottom.x} y2={bottom.y} stroke="#5a4632" strokeWidth={1.5} />,
      );
    }
  }

  const hLines = [];
  for (let r = 0; r < ROWS; r++) {
    const left = pointToPixel(r, 0, flipped);
    const right = pointToPixel(r, COLS - 1, flipped);
    hLines.push(<line key={`h${r}`} x1={left.x} y1={left.y} x2={right.x} y2={right.y} stroke="#5a4632" strokeWidth={1.5} />);
  }

  function palaceDiagonals(rowTop: number, rowBottom: number) {
    const a = pointToPixel(rowTop, 3, flipped);
    const b = pointToPixel(rowBottom, 5, flipped);
    const c = pointToPixel(rowTop, 5, flipped);
    const d = pointToPixel(rowBottom, 3, flipped);
    return (
      <>
        <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#5a4632" strokeWidth={1.5} />
        <line x1={c.x} y1={c.y} x2={d.x} y2={d.y} stroke="#5a4632" strokeWidth={1.5} />
      </>
    );
  }

  const riverY = (pointToPixel(4, 0, flipped).y + pointToPixel(5, 0, flipped).y) / 2;

  // --- coordinate labels ------------------------------------------------
  // Outer gutter: the a-i / 0-9 UCI coordinates that the 讲解 text cites.
  const fileLabels = [];
  const rankLabels = [];
  for (let c = 0; c < COLS; c++) {
    const { x } = pointToPixel(0, c, flipped);
    const letter = String.fromCharCode(97 + c);
    fileLabels.push(
      <text key={`ft${c}`} x={x} y={PAD * 0.62} textAnchor="middle" className="coord">{letter}</text>,
      <text key={`fb${c}`} x={x} y={HEIGHT - PAD * 0.3} textAnchor="middle" className="coord">{letter}</text>,
    );
  }
  for (let r = 0; r < ROWS; r++) {
    const { y } = pointToPixel(r, 0, flipped);
    const rank = String(9 - r);
    rankLabels.push(
      <text key={`rl${r}`} x={PAD * 0.55} y={y} textAnchor="middle" dominantBaseline="central" className="coord">{rank}</text>,
      <text key={`rr${r}`} x={WIDTH - PAD * 0.55} y={y} textAnchor="middle" dominantBaseline="central" className="coord">{rank}</text>,
    );
  }

  // Inner margin: 中文记谱 file numerals, on each side's own edge, since the
  // coaching text speaks in 炮二平五 / 马８进７. Red counts 一…九 from red's
  // right, black counts １…９ from black's right; both follow the flip.
  const redEdgeY = pointToPixel(9, 0, flipped).y;
  const blackEdgeY = pointToPixel(0, 0, flipped).y;
  const outward = redEdgeY > blackEdgeY ? 1 : -1;
  const numeralOffset = NUMERAL_OFFSET;
  const numerals = [];
  for (let c = 0; c < COLS; c++) {
    const { x } = pointToPixel(0, c, flipped);
    numerals.push(
      <text
        key={`nr${c}`}
        x={x}
        y={redEdgeY + outward * numeralOffset}
        textAnchor="middle"
        dominantBaseline="central"
        className="numeral numeral--red"
      >
        {RED_FILE_NUMERALS[c]}
      </text>,
      <text
        key={`nb${c}`}
        x={x}
        y={blackEdgeY - outward * numeralOffset}
        textAnchor="middle"
        dominantBaseline="central"
        className="numeral numeral--black"
      >
        {BLACK_FILE_NUMERALS[c]}
      </text>,
    );
  }

  const pieces = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const p = grid[r][c];
      if (!p) continue;
      const sq = squareName(r, c);
      const { x, y } = pointToPixel(r, c, flipped);
      pieces.push(
        <Piece key={sq} piece={p} x={x} y={y} r={CELL * 0.42} selected={selected === sq} onClick={() => handleSquareClick(sq)} />,
      );
    }
  }

  const clickTargets = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const sq = squareName(r, c);
      const { x, y } = pointToPixel(r, c, flipped);
      clickTargets.push(
        <circle
          key={`ct${sq}`}
          cx={x}
          cy={y}
          r={CELL * 0.46}
          fill="transparent"
          onClick={() => handleSquareClick(sq)}
          style={{ cursor: disabled ? "default" : "pointer" }}
        />,
      );
    }
  }

  function markerAt(square: string | undefined, color: string, key: string) {
    if (!square) return null;
    const [row, col] = squareToRC(square);
    const { x, y } = pointToPixel(row, col, flipped);
    return <rect key={key} x={x - CELL * 0.46} y={y - CELL * 0.46} width={CELL * 0.92} height={CELL * 0.92} fill="none" stroke={color} strokeWidth={3} rx={6} />;
  }

  function arrow(from: string | undefined, to: string | undefined, color: string) {
    if (!from || !to) return null;
    const [fr, fc] = squareToRC(from);
    const [tr, tc] = squareToRC(to);
    const p1 = pointToPixel(fr, fc, flipped);
    const p2 = pointToPixel(tr, tc, flipped);
    return (
      <line
        x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
        stroke={color} strokeWidth={5} strokeLinecap="round" opacity={0.75}
        markerEnd="url(#arrowhead)"
      />
    );
  }

  return (
    <svg
      width={height ? height * BOARD_ASPECT : WIDTH}
      height={height ?? HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ background: "#efe3c8", borderRadius: 10, border: "1px solid #d8c9a6", display: "block" }}
    >
      <style>{`
        .coord { font-size: 12px; fill: #9a8a6c; font-family: ui-monospace, monospace; user-select: none; }
        .numeral { font-size: 14px; user-select: none; font-weight: 600; }
        .numeral--red { fill: #b3261e; }
        .numeral--black { fill: #333; }
      `}</style>
      <defs>
        <marker id="arrowhead" markerWidth={10} markerHeight={10} refX={7} refY={5} orient="auto">
          <polygon points="0,0 10,5 0,10" fill="#2f6fed" opacity={0.85} />
        </marker>
      </defs>
      <rect
        x={PAD + MARGIN - 16}
        y={PAD + MARGIN - 16}
        width={GRID_W + 32}
        height={GRID_H + 32}
        rx={4}
        fill="#e8d3a3"
      />
      <rect x={PAD + MARGIN - 12} y={riverY - CELL / 2} width={GRID_W + 24} height={CELL} fill="#dcc493" />
      {vLines}
      {hLines}
      {palaceDiagonals(0, 2)}
      {palaceDiagonals(7, 9)}
      <text x={WIDTH * 0.33} y={riverY + 6} textAnchor="middle" fontSize={20} fill="#7a6440" style={{ userSelect: "none" }}>楚河</text>
      <text x={WIDTH * 0.67} y={riverY + 6} textAnchor="middle" fontSize={20} fill="#7a6440" style={{ userSelect: "none" }}>漢界</text>
      {fileLabels}
      {rankLabels}
      {numerals}
      {markerAt(lastMove?.from, "#7a9c59", "lm-from")}
      {markerAt(lastMove?.to, "#7a9c59", "lm-to")}
      {arrow(suggestedMove?.from, suggestedMove?.to, "#2f6fed")}
      {clickTargets}
      {pieces}
    </svg>
  );
}
