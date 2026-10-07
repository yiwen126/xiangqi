import { useEffect, useState } from "react";
import { BOARD_ASPECT, BOARD_HEIGHT } from "../components/Board";

/** Horizontal space the rest of the layout needs beside the board: eval bar,
 * the two side columns at their minimum widths, and the gaps between them. */
const RESERVED_W = 28 /* eval bar */ + 12 /* eval gap */ + 32 /* column gaps */ + 296 /* 讲解 col */ + 196 /* controls col */;
const RESERVED_H = 96; /* header + page padding */
const MIN_HEIGHT = 380;

/** The board is the only element that can absorb slack, so it is sized to
 * whatever is left after the panels get their minimums — that keeps 讲解 and
 * 候选着法 on screen without the page ever scrolling. */
export function useBoardFit(): number {
  const measure = () => {
    const availH = window.innerHeight - RESERVED_H;
    const availW = window.innerWidth - 40 - RESERVED_W;
    return Math.max(MIN_HEIGHT, Math.min(BOARD_HEIGHT, availH, availW / BOARD_ASPECT));
  };

  const [height, setHeight] = useState(measure);

  useEffect(() => {
    const onResize = () => setHeight(measure());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return height;
}
