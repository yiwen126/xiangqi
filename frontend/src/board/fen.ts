export type Grid = (string | null)[][]; // 10 rows x 9 cols, row0 = black back rank

export function parseFen(fen: string): Grid {
  const boardPart = fen.trim().split(" ")[0];
  const rows = boardPart.split("/");
  const grid: Grid = [];
  for (const rowStr of rows) {
    const row: (string | null)[] = [];
    for (const ch of rowStr) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < Number(ch); i++) row.push(null);
      } else {
        row.push(ch);
      }
    }
    grid.push(row);
  }
  return grid;
}

export function squareName(row: number, col: number): string {
  return `${String.fromCharCode(97 + col)}${9 - row}`;
}

export function squareToRC(square: string): [number, number] {
  const col = square.charCodeAt(0) - 97;
  const row = 9 - Number(square.slice(1));
  return [row, col];
}

export function isRed(piece: string): boolean {
  return piece === piece.toUpperCase();
}

export const PIECE_LABELS: Record<string, string> = {
  K: "帥", A: "仕", B: "相", N: "傌", R: "俥", C: "炮", P: "兵",
  k: "將", a: "士", b: "象", n: "馬", r: "車", c: "砲", p: "卒",
};
