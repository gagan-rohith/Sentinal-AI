import { useState } from "react";

import type { ApprovalRecord } from "../api";
import { Meter, Tag } from "./ui";

interface Props {
  approval: ApprovalRecord;
  busy: boolean;
  onDecide: (approve: boolean, text: string) => void;
}

export function ApprovalPanel({ approval, busy, onDecide }: Props) {
  const [text, setText] = useState("");
  const { request } = approval;
  return (
    <section className="card callout tone-warning approval">
      <h2>
        <span aria-hidden="true">! </span>Approval required before anything changes
      </h2>
      <p>
        The agents traced this to <strong>{request.root_cause}</strong> and want to make the
        changes below. Nothing runs until a person decides.
      </p>
      <Meter value={request.root_cause_confidence} label="confidence" />
      <h3>
        Proposed production changes <Tag tone={`risk-${request.overall_risk}`}>{request.overall_risk} risk</Tag>
      </h3>
      <ul className="plain actions-list">
        {request.actions.map((action) => (
          <li key={`${action.tool}-${JSON.stringify(action.arguments)}`}>
            <code className="action">
              {action.tool}(
              {Object.entries(action.arguments)
                .map(([k, v]) => `${k}=${v}`)
                .join(", ")}
              )
            </code>
            <Tag tone={`risk-${action.risk}`}>{action.risk}</Tag>
            <div className="muted small">{action.description}</div>
          </li>
        ))}
      </ul>
      <p className="muted small">Rollback: {request.rollback_plan}</p>
      {request.unresolved_critic_issues.length > 0 && (
        <div className="callout tone-critical">
          <strong>The critic did not approve this plan:</strong>
          <ul>
            {request.unresolved_critic_issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
      <label className="field">
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
      <p className="muted small">Approving needs an admin key; rejecting needs operator or above.</p>
    </section>
  );
}
