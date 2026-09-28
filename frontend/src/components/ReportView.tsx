import type { Evidence, FinalReport, Hypothesis } from "../api";

function Citations({ ids, evidence }: { ids: string[]; evidence: Map<string, Evidence> }) {
  if (ids.length === 0) return <span className="muted">none</span>;
  return (
    <>
      {ids.map((id) => (
        <abbr key={id} className="cite" title={evidence.get(id)?.summary ?? "unknown evidence"}>
          {id}
        </abbr>
      ))}
    </>
  );
}

function HypothesisRow({
  hypothesis,
  selected,
  evidence,
}: {
  hypothesis: Hypothesis;
  selected: boolean;
  evidence: Map<string, Evidence>;
}) {
  return (
    <tr className={selected ? "selected" : ""}>
      <td>
        <strong>{hypothesis.title}</strong>
        {hypothesis.category && <div className="muted">{hypothesis.category}</div>}
      </td>
      <td>{Math.round(hypothesis.confidence * 100)}%</td>
      <td>
        <Citations ids={hypothesis.evidence_for} evidence={evidence} />
      </td>
      <td>
        <Citations ids={hypothesis.evidence_against} evidence={evidence} />
      </td>
    </tr>
  );
}

export function ReportView({ report }: { report: FinalReport }) {
  const evidence = new Map(report.evidence.map((e) => [e.id, e]));
  const { postmortem, remediation_plan: plan } = report;
  return (
    <>
      <section className="card">
        <h2>Root cause</h2>
        <p>
          <strong>{report.selected_root_cause.title}</strong> with{" "}
          {Math.round(report.selected_root_cause.confidence * 100)}% confidence.
        </p>
        <p className="muted">
          Agents: {report.mode}. Critic: {report.critic_review?.verdict ?? "none"}
          {report.retries > 0 && `, ${report.retries} retries`}
          {report.unresolved_critic_issues && ", unresolved issues"}. Tool calls:{" "}
          {report.tool_call_count}.
        </p>
        <table>
          <thead>
            <tr>
              <th>Hypothesis</th>
              <th>Confidence</th>
              <th>Evidence for</th>
              <th>Evidence against</th>
            </tr>
          </thead>
          <tbody>
            {report.hypotheses.map((h) => (
              <HypothesisRow
                key={h.title}
                hypothesis={h}
                selected={h.title === report.selected_root_cause.title}
                evidence={evidence}
              />
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>Remediation</h2>
        <p>
          {plan.summary} Overall risk:{" "}
          <span className={`badge risk-${plan.overall_risk}`}>{plan.overall_risk}</span>
        </p>
        <ol>
          {plan.steps.map((step) => (
            <li key={step.description}>
              <span className="badge">{step.kind}</span> {step.description}
              {step.action && (
                <div>
                  <code>
                    {step.action.tool}({step.action.service}
                    {step.action.deployment_id ? `, ${step.action.deployment_id}` : ""})
                  </code>
                </div>
              )}
            </li>
          ))}
        </ol>
        <p className="muted">Rollback: {plan.rollback_plan}</p>
        <p>
          Approval: <strong>{report.approval_status}</strong>
          {report.approval &&
            ` by ${report.approval.decided_by}${report.approval.comment ? ` (${report.approval.comment})` : ""}`}
        </p>
        {report.executed_actions.map((a) => (
          <p key={a.tool}>
            Executed <code>{a.tool}</code>: {a.status}. {a.message}
          </p>
        ))}
      </section>

      <section className="card">
        <h2>Postmortem</h2>
        <h3>Summary</h3>
        <p>{postmortem.summary}</p>
        <h3>Impact</h3>
        <p>{postmortem.impact}</p>
        <h3>Timeline</h3>
        <ul className="timeline">
          {report.timeline.map((event) => (
            <li key={`${event.timestamp}-${event.source}`}>
              <time>{new Date(event.timestamp).toLocaleString()}</time> {event.description}
            </li>
          ))}
        </ul>
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
        {postmortem.open_questions.length > 0 && (
          <>
            <h3>Open questions</h3>
            <ul>
              {postmortem.open_questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>Evidence ({report.evidence.length})</h2>
        <ul className="evidence">
          {report.evidence.map((e) => (
            <li key={e.id}>
              <span className="cite">{e.id}</span> <span className="badge">{e.kind}</span>{" "}
              {e.summary}
            </li>
          ))}
        </ul>
        {report.trace_id && <p className="muted">Trace id: {report.trace_id}</p>}
      </section>
    </>
  );
}
