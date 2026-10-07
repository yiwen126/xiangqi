import type {
  GameRecord,
  GameSummary,
  LoadedGameResponse,
  MoveResultResponse,
  NoteResponse,
  PositionResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `请求失败：${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  newGame(fen?: string): Promise<PositionResponse> {
    return request("/game/new", { method: "POST", body: JSON.stringify({ fen: fen ?? null }) });
  },
  getPosition(): Promise<PositionResponse> {
    return request("/game/position");
  },
  makeMove(fromSq: string, toSq: string): Promise<MoveResultResponse> {
    return request("/game/move", {
      method: "POST",
      body: JSON.stringify({ from_sq: fromSq, to_sq: toSq }),
    });
  },
  engineMove(): Promise<MoveResultResponse> {
    return request("/game/engine_move", { method: "POST" });
  },
  /** 悔棋. `plies` lets an engine game step back past the engine's reply. */
  undo(plies = 1): Promise<PositionResponse> {
    return request("/game/undo", { method: "POST", body: JSON.stringify({ plies }) });
  },
  redo(plies = 1): Promise<PositionResponse> {
    return request("/game/redo", { method: "POST", body: JSON.stringify({ plies }) });
  },
  /** 另存为：copy the current line into a fresh library entry. The line does
   * not move, so this answers with a plain PositionResponse. */
  saveAs(name: string): Promise<PositionResponse> {
    return request("/game/save_as", { method: "POST", body: JSON.stringify({ name }) });
  },
  /** 打开对局：replay a saved game into the live session and return its whole
   * line. Works with the engine down. */
  openGame(id: string): Promise<LoadedGameResponse> {
    return request("/game/open", { method: "POST", body: JSON.stringify({ id }) });
  },
  /** 写笔记. `ply` is 1-based over the whole line (including the redo branch);
   * `null` writes the whole-game note. */
  setNote(ply: number | null, text: string): Promise<NoteResponse> {
    return request("/game/note", { method: "PUT", body: JSON.stringify({ ply, text }) });
  },
  /** 对局库列表, newest first. Works with the engine down. */
  listGames(): Promise<GameSummary[]> {
    return request("/games");
  },
  getGame(id: string): Promise<GameRecord> {
    return request(`/games/${encodeURIComponent(id)}`);
  },
  /** 导入复盘：`record` is the raw 对局文件 object, not a wrapper. */
  importGame(record: GameRecord): Promise<LoadedGameResponse> {
    return request("/games/import", { method: "POST", body: JSON.stringify(record) });
  },
  /** 重命名. Works on any saved game, not only the open one. */
  renameGame(id: string, name: string): Promise<GameSummary> {
    return request(`/games/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
  },
  /** 删除一局对局. The 409 protects the game currently open in the session;
   * the DELETE still answers a JSON body (`{"deleted": id}`) for `request`. */
  deleteGame(id: string): Promise<{ deleted: string }> {
    return request(`/games/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
  // NOTE: /game/goto is deliberately not exposed. It mutates the live backend
  // game, which lets the engine's auto-move fire from the browsed position.
  // History browsing is done client-side from cached move results.
};
