import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** A note target: the 1-based ply of the whole line, or `null` for 整局. */
type Target = number | null;

/** How long typing rests before it is written. */
const DEBOUNCE_MS = 500;

interface NotePanelProps {
  /** Which ply the viewer is on (0 = the start, before any move). */
  ply: number;
  /** "红 马八进七" for the displayed move, or null at ply 0. */
  moveLabel: string | null;
  /** One note per ply, exactly parallel to the move list. */
  notes: string[];
  gameNote: string;
  savedAt: string | null;
  saving: boolean;
  onSave: (ply: number | null, text: string) => void;
  onJump: (ply: number) => void;
}

/** HH:MM of the instant the record was written. `saved_at` is ISO 8601 in
 * local time with its offset (2026-10-05T22:56:22+08:00), so its time part is
 * the wall clock the player saw — no timezone arithmetic wanted here. */
function savedClock(iso: string | null): string | null {
  if (!iso) return null;
  const m = /T(\d{2}:\d{2})/.exec(iso);
  return m ? m[1] : null;
}

/** A note that is only whitespace counts as no note (共 N 条, the 整局 dot). */
function isBlank(text: string): boolean {
  return text.trim() === "";
}

export function NotePanel({
  ply,
  moveLabel,
  notes,
  gameNote,
  savedAt,
  saving,
  onSave,
  onJump,
}: NotePanelProps) {
  const [tab, setTab] = useState<"ply" | "game">("ply");
  const target: Target = tab === "game" ? null : ply;

  /** What the server currently holds for a target. */
  const storedText = (t: Target): string => (t === null ? gameNote : notes[t - 1] ?? "");

  /** Text written here that the server has not echoed back through `notes`
   * yet. A write only becomes visible in `notes` when its response lands, so
   * without this a switch back to a target mid-write would show the stale
   * pre-edit text. Keyed by target; entries are dropped once `notes` catches
   * up, and the map is cleared when the line itself is replaced. */
  const localDrafts = useRef(new Map<Target, string>());
  const lineLength = useRef(notes.length);
  if (lineLength.current !== notes.length) {
    localDrafts.current.clear(); // another line (opened record, branch, …)
    lineLength.current = notes.length;
  }

  /** The textarea's contents, and which target they belong to. Re-synced when
   * the target changes rather than reset from `notes` on every render, so a
   * response landing mid-typing cannot overwrite what is being typed. */
  const [draft, setDraft] = useState(() => localDrafts.current.get(target) ?? storedText(target));
  const [draftTarget, setDraftTarget] = useState<Target>(target);
  if (draftTarget !== target) {
    setDraftTarget(target);
    setDraft(localDrafts.current.get(target) ?? storedText(target));
  }

  /** The edit still inside the debounce window. It carries its own target, so
   * flushing it can only ever write the text to the ply it was typed on —
   * never to whatever the panel happens to display afterwards. */
  const pending = useRef<{ target: Target; text: string } | null>(null);
  const timer = useRef<number | null>(null);

  /** Latest `onSave` without making `flush` change identity (a changing flush
   * would re-run the unmount effect and flush mid-typing). */
  const saveRef = useRef(onSave);
  useEffect(() => {
    saveRef.current = onSave;
  }, [onSave]);

  const flush = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    const edit = pending.current;
    if (!edit) return;
    pending.current = null;
    saveRef.current(edit.target, edit.text);
  }, []);

  /** Switching tab or ply, blurring and unmounting all land a pending edit on
   * the target it was written for. Blur fires on mousedown, so clicking 打开 in
   * the library writes the note to the game it was typed in, before the click
   * swaps the line out from under it. Layout phase: its cleanup runs
   * synchronously with the switch, before any further keystroke or click can
   * interleave. */
  useLayoutEffect(() => flush, [flush, target]);

  /** Forget drafts the server has caught up with. */
  useEffect(() => {
    for (const [t, text] of localDrafts.current) {
      if (storedText(t) === text) localDrafts.current.delete(t);
    }
  });

  const edit = (text: string) => {
    setDraft(text);
    localDrafts.current.set(target, text);
    pending.current = { target, text };
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(flush, DEBOUNCE_MS);
  };

  const notedPlies = notes.flatMap((text, i) => (isBlank(text) ? [] : [i + 1]));
  const prevNoted = notedPlies.filter((p) => p < ply).pop();
  const nextNoted = notedPlies.find((p) => p > ply);

  const clock = savedClock(savedAt);
  const status = saving ? "保存中" : clock ? `已保存 ${clock}` : null;
  const tabClass = (active: boolean) => (active ? "note__tab note__tab--active" : "note__tab");

  return (
    <div className="card">
      <h3 className="card__title">
        笔记
        <span className="tag-opening">共 {notedPlies.length} 条</span>
        {status && <span className="note__status">{status}</span>}
      </h3>

      <div className="note__tabs">
        <button type="button" className={tabClass(tab === "ply")} onClick={() => setTab("ply")}>
          这一步
        </button>
        <button type="button" className={tabClass(tab === "game")} onClick={() => setTab("game")}>
          整局
          {!isBlank(gameNote) && <span className="note__dot" aria-hidden="true" />}
        </button>
      </div>

      {tab === "game" ? (
        <textarea
          className="note__editor"
          value={draft}
          onChange={(e) => edit(e.target.value)}
          onBlur={flush}
          placeholder="这一盘整体的思路、教训、下次要注意的地方。"
          aria-label="整局笔记"
        />
      ) : (
        <>
          <div className="note__head">
            <span className="note__target">
              {ply > 0 && `第 ${ply} 步${moveLabel ? ` · ${moveLabel}` : ""}`}
            </span>
            <button
              type="button"
              className="note__jump"
              onClick={() => prevNoted !== undefined && onJump(prevNoted)}
              disabled={prevNoted === undefined}
              title="跳到上一步有笔记的着法"
            >
              ◀
            </button>
            <button
              type="button"
              className="note__jump"
              onClick={() => nextNoted !== undefined && onJump(nextNoted)}
              disabled={nextNoted === undefined}
              title="跳到下一步有笔记的着法"
            >
              ▶
            </button>
          </div>
          {ply === 0 ? (
            <div className="note__hint">走到某一步或在上面的棋谱里点一步，就能给它写笔记。</div>
          ) : (
            <textarea
              className="note__editor"
              value={draft}
              onChange={(e) => edit(e.target.value)}
              onBlur={flush}
              placeholder="这一步的想法、疑问，或者下次要改的地方。"
              aria-label={`第 ${ply} 步的笔记`}
            />
          )}
        </>
      )}
    </div>
  );
}
