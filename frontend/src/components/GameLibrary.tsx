import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { GameRecord, GameStatus, GameSummary, Side } from "../api/types";

interface GameLibraryProps {
  /** Whether the modal is showing. It stays mounted while closed so the list
   * is fetched afresh on every open. */
  open: boolean;
  /** The game open in the session — 删除 is disabled for it, because its file
   * is being auto-saved into (the server answers 409). */
  currentId: string | null;
  /** A move/open/import is already in flight: 打开 / 导入 / 另存为 would
   * silently no-op (the hook drops them while busy). */
  busy: boolean;
  onClose: () => void;
  /** Each of these answers null on success, or the Chinese failure message —
   * in which case the modal stays open and shows it. */
  onOpen: (id: string) => Promise<string | null>;
  onImport: (record: GameRecord) => Promise<string | null>;
  onSaveAs: (name: string) => Promise<string | null>;
  /** Report a failure to the page as well as in here, so it is still visible
   * after the modal closes. */
  onError: (message: string) => void;
  /** The open game was renamed here: the session's name has to follow. */
  onRenamed: (id: string, name: string) => void;
}

const SIDE_CN: Record<Side, string> = { w: "红方", b: "黑方" };

/** What the row's result cell says. A library row has room for the outcome,
 * not for the sentence GameStatus renders. */
function resultLabel(status: GameStatus, winner: Side | null): string {
  switch (status) {
    case "checkmate":
    case "stalemate":
      return winner ? `${SIDE_CN[winner]}胜` : "已结束";
    case "perpetual_loss":
      return winner ? `长将判负 · ${SIDE_CN[winner]}胜` : "长将判负";
    case "draw_repetition":
      return "和棋";
    default:
      return "进行中";
  }
}

/** 「2026-10-05 23:15」 — `updated_at` is ISO 8601 with the local offset, so its
 * first 16 characters are the wall clock the file was last written. */
function stamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

/** The game's name as a filename: anything outside `[\w一-龥 -]` — `:` `/`
 * `\` `*` and the rest — becomes `_`. Never empty, so the download always has
 * a name. */
function safeFileName(name: string): string {
  const cleaned = name.replace(/[^\w一-龥 -]/g, "_").trim();
  return cleaned === "" ? "对局" : cleaned;
}

/** 对局库: browse, rename, export, delete and import the saved games. */
export function GameLibrary({
  open,
  currentId,
  busy,
  onClose,
  onOpen,
  onImport,
  onSaveAs,
  onError,
  onRenamed,
}: GameLibraryProps) {
  const [games, setGames] = useState<GameSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** One of this modal's own requests is in flight (rename/delete/export). */
  const [pending, setPending] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [saveAsName, setSaveAsName] = useState("");
  /** The id whose 删除 has been armed by a first click. Deleting a file cannot
   * be undone, so it takes a second click on the same row. */
  const [armedDelete, setArmedDelete] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  /** Orders list fetches so a slow earlier response cannot overwrite a newer list. */
  const listSeq = useRef(0);

  /** `onError` is a prop that may be an inline lambda; keeping the latest in a
   * ref lets `fail` stay stable, so the fetch-on-open effect below cannot
   * re-run on every parent render. */
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const fail = useCallback((e: unknown) => {
    const message = e instanceof Error ? e.message : String(e);
    setError(message);
    onErrorRef.current(message);
  }, []);

  const refresh = useCallback(async () => {
    const seq = ++listSeq.current;
    try {
      const list = await api.listGames();
      if (seq === listSeq.current) setGames(list);
    } catch (e) {
      if (seq === listSeq.current) fail(e);
    }
  }, [fail]);

  /** A fresh list on every open; nothing typed in a previous visit survives. */
  useEffect(() => {
    if (!open) return;
    setGames(null);
    setError(null);
    setRenaming(null);
    setNameDraft("");
    setSaveAsName("");
    setArmedDelete(null);
    void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const blocked = busy || pending;

  const openGame = async (id: string) => {
    if (blocked) return;
    // Stay open on a failure (404, unreadable file, invalid line): the message
    // belongs next to the row that was clicked, not on a page the player may
    // have scrolled away from.
    const message = await onOpen(id);
    if (message) {
      fail(message);
      return;
    }
    onClose();
  };

  const startRename = (game: GameSummary) => {
    setArmedDelete(null);
    setError(null);
    setRenaming(game.id);
    setNameDraft(game.name);
  };

  const commitRename = async () => {
    const name = nameDraft.trim();
    if (renaming === null || name === "" || blocked) return;
    setPending(true);
    setError(null);
    try {
      const updated = await api.renameGame(renaming, name);
      setRenaming(null);
      onRenamed(updated.id, updated.name); // the session's name follows the file
      await refresh();
    } catch (e) {
      fail(e); // stay in edit mode: the name can still be fixed
    } finally {
      setPending(false);
    }
  };

  const exportGame = async (game: GameSummary) => {
    if (blocked) return;
    setArmedDelete(null);
    setPending(true);
    setError(null);
    try {
      const record = await api.getGame(game.id);
      const blob = new Blob([JSON.stringify(record, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeFileName(record.name)}.xqsf.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Some browsers cancel a download whose blob URL is revoked in the same
      // task, so let the click's download start first.
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (e) {
      fail(e);
    } finally {
      setPending(false);
    }
  };

  const removeGame = async (game: GameSummary) => {
    if (blocked || game.id === currentId) return;
    if (armedDelete !== game.id) {
      setArmedDelete(game.id);
      return;
    }
    setPending(true);
    setError(null);
    try {
      await api.deleteGame(game.id);
      setArmedDelete(null);
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setPending(false);
    }
  };

  const importFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      let record: GameRecord;
      try {
        record = JSON.parse(String(reader.result)) as GameRecord;
      } catch {
        fail("这个文件不是有效的 JSON，无法导入。");
        return;
      }
      // The file is already read, so a rejection (a 400 from the store) keeps
      // the modal open with the message and the player can pick another file.
      void (async () => {
        const message = await onImport(record);
        if (message) {
          fail(message);
          return;
        }
        onClose(); // the imported game replaces the session
      })();
    };
    reader.onerror = () => fail("读取文件失败，请再试一次。");
    reader.readAsText(file);
  };

  const pickFile = () => {
    if (blocked) return;
    setArmedDelete(null);
    fileInput.current?.click();
  };

  const saveCopy = async () => {
    const name = saveAsName.trim();
    if (name === "" || blocked) return;
    // 400 「还没有走子，无法另存为」 and friends: keep the modal — and the typed
    // name — instead of closing on a save that never happened.
    const message = await onSaveAs(name);
    if (message) {
      fail(message);
      return;
    }
    onClose();
  };

  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="对局库"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h3 className="card__title">对局库</h3>
          <button className="btn" onClick={onClose}>关闭</button>
        </div>

        <div className="modal__saveas">
          <label htmlFor="lib-saveas">另存为</label>
          <input
            id="lib-saveas"
            className="modal__input"
            value={saveAsName}
            disabled={busy}
            placeholder="给这盘棋起个名字"
            onChange={(e) => setSaveAsName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void saveCopy();
            }}
          />
          <button
            className="btn"
            onClick={() => void saveCopy()}
            disabled={blocked || saveAsName.trim() === ""}
            title="把当前这盘棋复制成对局库里的另一局"
          >
            保存副本
          </button>
        </div>

        {error && <div className="modal__error">{error}</div>}

        <div className="modal__list">
          {games === null ? (
            <div className="modal__empty">{error ? "对局库读取失败。" : "载入中…"}</div>
          ) : games.length === 0 ? (
            <div className="modal__empty">对局库还是空的：走出第一步棋，这盘棋就会自动保存在这里。</div>
          ) : (
            games.map((game) => {
              const isCurrent = game.id === currentId;
              const armed = armedDelete === game.id;

              if (renaming === game.id) {
                return (
                  <div key={game.id} className="lib__row">
                    <input
                      className="modal__input lib__rename"
                      value={nameDraft}
                      autoFocus
                      disabled={pending}
                      aria-label="新的名字"
                      onChange={(e) => setNameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void commitRename();
                        if (e.key === "Escape") {
                          e.stopPropagation(); // 取消 the rename, not the modal
                          setRenaming(null);
                        }
                      }}
                    />
                    <div className="lib__actions">
                      <button
                        className="btn"
                        onClick={() => void commitRename()}
                        disabled={blocked || nameDraft.trim() === ""}
                      >
                        确定
                      </button>
                      <button className="btn" onClick={() => setRenaming(null)} disabled={pending}>
                        取消
                      </button>
                    </div>
                  </div>
                );
              }

              return (
                <div key={game.id} className="lib__row">
                  <div className="lib__info">
                    <div className="lib__name">
                      <span className="lib__name-text" title={game.name || "无名对局"}>
                        {game.name || "无名对局"}
                      </span>
                      {isCurrent && <span className="lib__current">当前对局</span>}
                    </div>
                    <div className="lib__meta">
                      {stamp(game.updated_at)} · {game.move_count} 步 · {game.note_count} 条笔记
                    </div>
                  </div>

                  <span
                    className={
                      game.result === "ongoing" ? "lib__result" : "lib__result lib__result--done"
                    }
                  >
                    {resultLabel(game.result, game.winner)}
                  </span>

                  <div className="lib__actions">
                    <button
                      className="btn"
                      onClick={() => void openGame(game.id)}
                      disabled={blocked}
                      title="打开这局：回看整盘棋，也可以接着走"
                    >
                      打开
                    </button>
                    <button className="btn" onClick={() => startRename(game)} disabled={blocked}>
                      改名
                    </button>
                    <button
                      className="btn"
                      onClick={() => void exportGame(game)}
                      disabled={blocked}
                      title="导出为 .xqsf.json 文件"
                    >
                      导出
                    </button>
                    <button
                      className={armed ? "btn btn--danger" : "btn"}
                      onClick={() => void removeGame(game)}
                      disabled={isCurrent || blocked}
                      title={
                        isCurrent
                          ? "这是当前对局，请先开新对局"
                          : armed
                            ? "再点一次就删除"
                            : "删除这一局"
                      }
                    >
                      {armed ? "确定删除" : "删除"}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="modal__foot">
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = ""; // the same file can be picked again after a failure
              if (file) importFile(file);
            }}
          />
          <button className="btn" onClick={pickFile} disabled={blocked}>
            从文件导入
          </button>
          <span className="modal__foot-hint">
            正在对局的那盘棋不能删除；导出的文件可以再导入回来。
          </span>
        </div>
      </div>
    </div>
  );
}
