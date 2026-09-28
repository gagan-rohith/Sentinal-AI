import type { RunRecord } from "../api";

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
    <div className="pipeline" aria-label="Agent stages">
      {STAGES.map(([name, label], index) => {
        let state = "pending";
        if (done || index < current) state = "done";
        else if (index === current) state = run.status === "failed" ? "failed" : "active";
        return (
          <span key={name} className={`stage ${state}`}>
            {label}
          </span>
        );
      })}
      <span className="muted run-meta">
        {run.run_id}, {run.status}
        {run.retry_count > 0 && `, ${run.retry_count} critic retries`}
      </span>
    </div>
  );
}
