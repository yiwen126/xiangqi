export type Side = "w" | "b";

export type GameStatus =
  | "ongoing"
  | "checkmate"
  | "stalemate"
  | "draw_repetition"
  | "perpetual_loss";

export interface PvLine {
  multipv: number;
  score_cp: number | null;
  score_mate: number | null;
  pv: string[];
}

export interface Tactic {
  kind: string;
  side: Side;
  piece: string;
  piece_name: string;
  square: string;
  square_chinese: string | null;
  targets: string[];
  targets_chinese: string[] | null;
}

export interface Intent {
  kind: "attack" | "defend" | "goal";
  text: string;
  piece: string;
  piece_name: string;
  square: string;
  square_chinese: string | null;
  targets: string[];
  targets_chinese: string[];
}

export interface FollowUp {
  moves_uci: string[];
  moves_chinese: (string | null)[];
}

/** Up to ten consecutive moves for the mover in the hypothetical where the
 * opponent keeps passing (chained side-flipped "null move" positions);
 * display-only. */
export interface PassingPlan {
  moves_uci: string[];
  moves_chinese: (string | null)[];
}

/** One of the engine's top choices for the position *before* the played move.
 * `score_cp` / `score_mate` are from the MOVER's point of view (see api-contract.md). */
export interface Candidate {
  rank: number;
  move_uci: string;
  move_chinese: string | null;
  score_cp: number | null;
  score_mate: number | null;
  pv_uci: string[];
  pv_chinese: (string | null)[];
  is_played: boolean;
}

export interface PositionResponse {
  fen: string;
  side_to_move: Side;
  game_status: GameStatus;
  in_check: boolean;
  winner: Side | null;
  result_note: string | null;
  move_history: string[];
  move_history_chinese: (string | null)[];
  future_moves: string[];
  /** One entry per ply of the whole line, parallel to
   * `move_history + future_moves` — the applied moves first, then the undone
   * ones in play order. `""` means no note on that ply. */
  notes: string[];
  /** The note on the game as a whole; `""` when none. */
  game_note: string;
  /** The 对局库 identity of the game in flight. Both are null until the first
   * move auto-creates the record, and after 新对局. */
  game_id: string | null;
  game_name: string | null;
  /** When the record was last written (ISO 8601); null before the first save
   * or when auto-save is unavailable. */
  saved_at: string | null;
  /** Non-null when the last auto-save failed; the move still stands and play
   * continues from memory. */
  save_error: string | null;
  lines: PvLine[];
}

/** The note line as it stands after a write. A note changes neither the
 * position nor the engine output, so there is nothing else to return. */
export interface NoteResponse {
  notes: string[];
  game_note: string;
  saved_at: string | null;
  save_error: string | null;
}

export interface PlyView {
  move_uci: string;
  move_chinese: string | null;
  fen: string;         // the position AFTER this ply
  side_to_move: Side;  // the side to move AFTER this ply
}

/** `PositionResponse` plus the whole saved line, answered only by 打开/导入.
 * Each ply carries the position *after* it, so an opened game can be stepped
 * through without replaying the moves client-side. */
export type LoadedGameResponse = PositionResponse & { plies: PlyView[] };

export interface MoveResultResponse {
  fen: string;
  side_to_move: Side;
  move_uci: string;
  move_chinese: string | null;
  played_matches_best: boolean;
  best_move_uci: string | null;
  best_move_chinese: string | null;
  label: string;
  label_en: string;
  color: string;
  cp_loss: number;
  eval_cp: number | null;
  candidates: Candidate[];
  why_better: string | null;
  intent_text: string | null;
  intents: Intent[];
  follow_up: FollowUp | null;
  passing_plan: PassingPlan | null;
  best_passing_plan: PassingPlan | null;
  explanation: string;
  tactics: Tactic[];
  opening_name: string | null;
  opening_note: string | null;
  in_book: boolean;
  left_book_now: boolean;
  game_status: GameStatus;
  result_note: string | null;
  in_check: boolean;
  winner: Side | null;
  // The same auto-save identity fields as PositionResponse: this move has just
  // been mirrored into the record, or its save failed and is reported here.
  game_id: string | null;
  game_name: string | null;
  saved_at: string | null;
  save_error: string | null;
}

/** A ply from a game opened off disk: position, notation and notes only.
 * Engine analysis is regenerated only for moves played in this session. */
export type PlyEntry = MoveResultResponse & { loaded_only?: boolean };

/** A 对局库 list row — enough to render the library without loading a game. */
export interface GameSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  move_count: number;
  note_count: number;
  result: GameStatus;
  winner: Side | null;
}

/** One 对局文件 as exported by `GET /games/{id}`. It holds only the player's
 * own game — engine output is recomputed, never stored. */
export interface GameRecord {
  format: string;
  version: number;
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  start_fen: string | null;
  moves: string[];
  notes: string[];
  game_note: string;
  result: GameStatus;
  winner: Side | null;
}
