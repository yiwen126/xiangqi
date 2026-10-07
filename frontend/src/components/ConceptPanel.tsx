import type { Intent, PassingPlan, PlyEntry } from "../api/types";

interface ConceptPanelProps {
  move: PlyEntry | null;
}

const INTENT_LABELS: Record<Intent["kind"], string> = {
  attack: "攻",
  defend: "守",
  goal: "目的",
};

/** The opponent-keeps-passing chain for a move — up to ten consecutive own
 * moves, separated by arrows. */
function PassingLine({ plan }: { plan: PassingPlan | null }) {
  if (!plan || plan.moves_uci.length === 0) return null;
  return (
    <div className="followup__line followup__line--pass">
      <span className="cand__pv-label">若对方不应</span>
      {plan.moves_uci.map((uci, i) => (
        <span key={i}>
          {i > 0 && " → "}
          {plan.moves_chinese[i] ?? uci}
        </span>
      ))}
    </div>
  );
}

/** The backend's `explanation` is the full paragraph and already contains
 * `why_better` / `intent_text` / `opening_note` verbatim. We render those as
 * their own scannable blocks, so strip them out of the paragraph to avoid
 * showing the same sentence twice. */
function summaryOf(move: PlyEntry): string {
  let text = move.explanation;
  for (const part of [move.why_better, move.intent_text, move.opening_note]) {
    if (part && text.includes(part)) text = text.replace(part, "");
  }
  return text.replace(/\s+/g, " ").trim();
}

export function ConceptPanel({ move }: ConceptPanelProps) {
  if (!move) {
    return (
      <div className="card" style={{ minHeight: 150 }}>
        <h3 className="card__title">讲解</h3>
        <div className="concept__placeholder">走一步棋，这里会显示对这步棋的讲解。</div>
      </div>
    );
  }

  // A ply opened off disk carries its board and notation but no engine output:
  // the coaching card would otherwise explain nothing in an empty paragraph.
  // The move's identity still belongs here — only the analysis is missing.
  if (move.loaded_only) {
    return (
      <div className="card" style={{ minHeight: 150 }}>
        <h3 className="card__title concept__head">
          讲解
          <span className="concept__move">{move.move_chinese ?? move.move_uci}</span>
          <span className="cand__uci">{move.move_uci}</span>
        </h3>
        <div className="concept__placeholder">
          这是从对局库打开的棋谱：可以逐步回看、写笔记；引擎讲解只为你在这里走的棋生成。
        </div>
      </div>
    );
  }

  const followUp = move.follow_up;
  const passingPlan = move.passing_plan;
  const bestPassingPlan = move.best_passing_plan;

  return (
    <div className="card" style={{ minHeight: 150 }}>
      {/* Two rows: the move's identity, then its opening context. Cramming all
          six items onto one line wraps 马八进七 mid-word in a narrow column. */}
      <h3 className="card__title concept__head">
        讲解
        <span className="badge" style={{ background: move.color }}>{move.label}</span>
        <span className="concept__move">{move.move_chinese ?? move.move_uci}</span>
        <span className="cand__uci">{move.move_uci}</span>
      </h3>
      {(move.opening_name || move.left_book_now) && (
        <div className="concept__tags">
          {move.opening_name && <span className="tag-opening">开局：{move.opening_name}</span>}
          {move.left_book_now && <span className="tag-left-book">已离开理论</span>}
        </div>
      )}

      <p className="concept__text">{summaryOf(move)}</p>

      {move.intents.length > 0 && (
        <div className="concept__block concept__block--intent">
          <div className="concept__block-title">这步棋的意图</div>
          {move.intents.map((it, i) => (
            <div key={i} className="intent__row">
              <span className={`intent__tag intent__tag--${it.kind}`}>{INTENT_LABELS[it.kind]}</span>
              <span>{it.text}</span>
            </div>
          ))}
        </div>
      )}

      {(followUp || passingPlan) && (
        <div className="concept__block concept__block--followup">
          <div className="concept__block-title">后续变化（引擎）</div>
          {followUp && followUp.moves_uci.length > 0 && (
            <div className="followup__line">
              {followUp.moves_uci.map((uci, i) => (
                <span key={i}>
                  {i > 0 && " → "}
                  {i % 2 === 0 ? "对方 " : "你 "}
                  {followUp.moves_chinese[i] ?? uci}
                </span>
              ))}
            </div>
          )}
          <PassingLine plan={passingPlan} />
        </div>
      )}

      {move.why_better && (
        <div className="concept__block concept__block--better">
          <div className="concept__block-title">
            更好的选择：{move.best_move_chinese ?? move.best_move_uci}
          </div>
          {move.why_better}
          <PassingLine plan={bestPassingPlan} />
        </div>
      )}

      {move.opening_note && (
        <div className="concept__block concept__block--opening">
          <div className="concept__block-title">开局：{move.opening_name}</div>
          {move.opening_note}
        </div>
      )}
    </div>
  );
}
