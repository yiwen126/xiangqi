import type { Candidate } from "../api/types";

interface CandidatePanelProps {
  candidates: Candidate[];
}

/** Scores are from the MOVER's point of view (see docs/api-contract.md). */
function formatScore(c: Candidate): string {
  if (c.score_mate != null) {
    return c.score_mate > 0 ? `${c.score_mate} 步杀` : `被杀 ${Math.abs(c.score_mate)} 步`;
  }
  if (c.score_cp == null) return "—";
  const v = c.score_cp / 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}

/** The follow-up plan, skipping the candidate move itself (already shown above). */
function formatPv(c: Candidate): string {
  return c.pv_chinese
    .slice(1)
    .map((m, i) => m ?? c.pv_uci[i + 1] ?? "")
    .filter(Boolean)
    .join("  ");
}

export function CandidatePanel({ candidates }: CandidatePanelProps) {
  if (candidates.length === 0) {
    return (
      <div className="card">
        <h3 className="card__title">候选着法</h3>
        <div className="concept__placeholder">走一步棋，这里会列出引擎认为最好的几种下法。</div>
      </div>
    );
  }

  return (
    <div className="card">
      <h3 className="card__title">
        候选着法
        <span className="tag-opening">引擎首选在最上方</span>
      </h3>
      {candidates.map((c) => {
        const cls = [
          "cand",
          c.rank === 1 ? "cand--best" : "",
          c.is_played ? "cand--played" : "",
        ].filter(Boolean).join(" ");
        const pv = formatPv(c);
        return (
          <div key={c.rank} className={cls}>
            <div className="cand__head">
              <span className="cand__rank">{c.rank}</span>
              <span className="cand__move">{c.move_chinese ?? c.move_uci}</span>
              <span className="cand__uci">{c.move_uci}</span>
              {c.is_played && <span className="cand__tag">你走的</span>}
              <span className="cand__score">{formatScore(c)}</span>
            </div>
            {pv && (
              <div className="cand__pv">
                <span className="cand__pv-label">后续</span>
                {pv}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
