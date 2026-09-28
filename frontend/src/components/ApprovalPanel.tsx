import { useState } from "react";

import type { ApprovalRecord } from "../api";

interface Props {
  approval: ApprovalRecord;
  busy: boolean;
  onDecide: (approve: boolean, text: string) => void;
}

export function ApprovalPanel({ approval, busy, onDecide }: Props) {
  const [text, setText] = useState("");
  const { request } = approval;
  return (
    <section className="card approval">
      <h2>Approval required</h2>
      <p>
        Root cause: <strong>{request.root_cause}</strong> (confidence{" "}
        {Math.round(request.root_cause_confidence * 100)}%). Overall risk:{" "}
        <span className={`badge risk-${request.overall_risk}`}>{request.overall_risk}</span>
      </p>
      <h3>Proposed production changes</h3>
      <ul>
        {request.actions.map((action) => (
          <li key={`${action.tool}-${JSON.stringify(action.arguments)}`}>
            <code>
              {action.tool}({Object.entries(action.arguments).map(([k, v]) => `${k}=${v}`).join(", ")})
            </code>{" "}
            <span className={`badge risk-${action.risk}`}>{action.risk}</span>
            <div className="muted">{action.description}</div>
          </li>
        ))}
      </ul>
      <p className="muted">Rollback: {request.rollback_plan}</p>
      {request.unresolved_critic_issues.length > 0 && (
        <div className="warning">
          The critic did not approve this plan:
          <ul>
            {request.unresolved_critic_issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
      <label>
        Comment (required to reject)
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Why approve or reject"
        />
      </label>
      <div className="actions">
        <button type="button" disabled={busy} onClick={() => onDecide(true, text)}>
          Approve and execute
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || text.trim().length < 3}
          onClick={() => onDecide(false, text)}
        >
          Reject
        </button>
      </div>
      <p className="muted">Approving needs an admin key; rejecting needs operator or above.</p>
    </section>
  );
}
