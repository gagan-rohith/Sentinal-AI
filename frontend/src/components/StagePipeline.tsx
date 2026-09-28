import type { RunRecord } from "../api";
import { StatusBadge } from "./ui";

// Graph nodes in execution order. The run record's `stage` is the last node that finished.
const STAGES = [
  ["triage", "Triage"],
  ["context_collection", "Context"],
  ["retrieval", "Retrieval"],
  ["root_cause", "Root cause"],
  ["remediation", "Remediation"],
  ["critic", "Critic"],
  ["human_approval", "Approval"],
  ["action_execution", "Execution"],
  ["postmortem", "Postmortem"],
] as const;

export function StagePipeline({ run }: { run: RunRecord }) {
  const done = run.status === "completed";
  const current = STAGES.findIndex(([name]) => name === run.stage);
  return (
    <section className="card pipeline-card" aria-label="Agent progress">
      <div className="card-head">
        <h2>Agent progress</h2>
        <StatusBadge status={run.status} />
      </div>
      <ol className="stepper">
        {STAGES.map(([name, label], index) => {
          let state = "pending";
          if (done || index < current) state = "done";
          else if (index === current) {
            if (run.status === "failed") state = "failed";
            else if (run.status === "awaiting_approval") state = "waiting";
            else state = "active";
          }
          return (
            <li key={name} className={`step ${state}`}>
              <span className="step-dot" aria-hidden="true" />
              <span className="step-label">{label}</span>
            </li>
          );
        })}
      </ol>
      <p className="muted small">
        Run {run.run_id}
        {run.retry_count > 0 && `, the critic sent work back ${run.retry_count} times`}
      </p>
    </section>
  );
}
