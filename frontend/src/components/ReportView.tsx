import type { Evidence, FinalReport, Hypothesis } from "../api";
import { dateTime, percent } from "../format";
import { EvidenceChip, Meter, Tag } from "./ui";

const KIND_LABELS: [string, string][] = [
  ["health", "Service health"],
  ["log", "Error logs"],
  ["metric", "Metric anomalies"],
  ["change", "Recent changes"],
  ["deployment", "Deployments"],
  ["runbook", "Runbooks"],
  ["incident", "Similar past incidents"],
  ["service_doc", "Service documentation"],
];

function Citations({ ids, evidence }: { ids: string[]; evidence: Map<string, Evidence> }) {
  if (ids.length === 0) return <span className="muted small">none</span>;
  return (
    <span className="chips">
      {ids.map((id) => (
        <EvidenceChip key={id} id={id} summary={evidence.get(id)?.summary} />
      ))}
    </span>
  );
}

function isRuledOut(h: Hypothesis): boolean {
  return h.confidence === 0 || h.evidence_against.length > h.evidence_for.length;
}

function Chapter({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="card chapter">
      <h2>
        <span className="chapter-n">{n}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function ReportView({ report }: { report: FinalReport }) {
  const evidence = new Map(report.evidence.map((e) => [e.id, e]));
  const { postmortem, remediation_plan: plan, selected_root_cause: selected } = report;
  const hypotheses = [...report.hypotheses].sort((a, b) => b.confidence - a.confidence);
  const groups = KIND_LABELS.map(([kind, label]) => ({
    label,
    items: report.evidence.filter((e) => e.kind === kind),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="story">
      <section className="card verdict">
        <div className="verdict-label">Root cause</div>
        <div className="verdict-title">{selected.title}</div>
        <Meter value={selected.confidence} label="confidence" />
        <p className="muted small">
          Chosen from {report.hypotheses.length} hypotheses using {report.evidence.length} pieces
          of evidence and {report.tool_call_count} tool calls. Agents ran in {report.mode} mode
          {report.retries > 0 && `; the critic asked for ${report.retries} revisions`}.
        </p>
      </section>

      <Chapter n={1} title="What happened">
        <p>{postmortem.summary}</p>
        <p className="impact">{postmortem.impact}</p>
        <ol className="timeline">
          {report.timeline.map((event) => (
            <li key={`${event.timestamp}-${event.source}`}>
              <time>{dateTime(event.timestamp)}</time>
              <span>{event.description}</span>
            </li>
          ))}
        </ol>
      </Chapter>

      <Chapter n={2} title="Evidence gathered">
        <div className="evidence-groups">
          {groups.map((group) => (
            <details key={group.label} open={group.items.length <= 6}>
              <summary>
                {group.label} <span className="muted">({group.items.length})</span>
              </summary>
              <ul>
                {group.items.map((e) => (
                  <li key={e.id}>
                    <EvidenceChip id={e.id} summary={e.summary} />
                    <span>{e.summary}</span>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      </Chapter>

      <Chapter n={3} title="Hypotheses considered">
        <div className="hypotheses">
          {hypotheses.map((h) => {
            const chosen = h.title === selected.title;
            const ruledOut = !chosen && isRuledOut(h);
            return (
              <article
                key={h.title}
                className={`hypothesis${chosen ? " chosen" : ""}${ruledOut ? " ruled-out" : ""}`}
              >
                <header>
                  <strong>{h.title}</strong>
                  {chosen && <Tag tone="good">Selected</Tag>}
                  {ruledOut && <Tag tone="neutral">Ruled out</Tag>}
                </header>
                <Meter value={h.confidence} label="confidence" />
                <p className="small">{h.description}</p>
                <div className="cites">
                  <span className="muted small">For</span>
                  <Citations ids={h.evidence_for} evidence={evidence} />
                  <span className="muted small">Against</span>
                  <Citations ids={h.evidence_against} evidence={evidence} />
                </div>
              </article>
            );
          })}
        </div>
      </Chapter>

      <Chapter n={4} title="Decision">
        <p>
          {plan.summary} Overall risk: <Tag tone={`risk-${plan.overall_risk}`}>{plan.overall_risk}</Tag>
        </p>
        <ol className="steps">
          {plan.steps.map((step) => (
            <li key={step.description}>
              <div className="step-head">
                <Tag>{step.kind}</Tag>
                {step.action && <Tag tone="warning">changes production</Tag>}
              </div>
              <span>{step.description}</span>
              {step.action && (
                <code className="action">
                  {step.action.tool}({step.action.service}
                  {step.action.deployment_id ? `, ${step.action.deployment_id}` : ""})
                </code>
              )}
            </li>
          ))}
        </ol>
        <div className={`outcome tone-${report.approval_status === "approved" ? "good" : report.approval_status === "rejected" ? "critical" : "neutral"}`}>
          <strong>
            Human decision: <span className="cap">{report.approval_status.replace("_", " ")}</span>
          </strong>
          {report.approval && (
            <span>
              {" "}
              by {report.approval.decided_by}
              {report.approval.comment && `: "${report.approval.comment}"`}
            </span>
          )}
          {report.executed_actions.map((a) => (
            <div key={a.tool}>
              <code>{a.tool}</code> {a.status}. {a.message}
            </div>
          ))}
        </div>
        <p className="muted small">Rollback plan: {plan.rollback_plan}</p>
      </Chapter>

      <Chapter n={5} title="Follow-up">
        {postmortem.prevention.length > 0 && (
          <>
            <h3>Prevention</h3>
            <ul>
              {postmortem.prevention.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </>
        )}
        <h3>Open questions</h3>
        {postmortem.open_questions.length > 0 ? (
          <ul>
            {postmortem.open_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        ) : (
          <p className="muted small">None recorded.</p>
        )}
        {report.critic_review && (
          <p className="muted small">
            Critic verdict: {report.critic_review.verdict} (confidence{" "}
            {percent(report.critic_review.confidence)})
            {report.unresolved_critic_issues && ", with unresolved issues"}.
          </p>
        )}
        {report.trace_id && <p className="muted small">Trace id {report.trace_id}</p>}
      </Chapter>
    </div>
  );
}
