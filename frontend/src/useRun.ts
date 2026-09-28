import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, type ApprovalRecord, type FinalReport, type RunRecord } from "./api";

const POLL_MS = 700;

export interface RunState {
  run: RunRecord | null;
  approval: ApprovalRecord | null;
  report: FinalReport | null;
  error: string | null;
  busy: boolean;
}

const EMPTY: RunState = { run: null, approval: null, report: null, error: null, busy: false };

function message(error: unknown): string {
  if (error instanceof ApiError) {
    const trace = error.traceId ? ` (trace ${error.traceId})` : "";
    return `${error.status} ${error.code}: ${error.message}${trace}`;
  }
  return error instanceof Error ? error.message : String(error);
}

// Starts an analysis and follows it: polls while it runs, loads the approval request
// when it pauses, and loads the report when it completes.
export function useRun(apiKey: string) {
  const [state, setState] = useState<RunState>(EMPTY);
  const timer = useRef<number | null>(null);

  const stop = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  };

  const follow = useCallback(
    async (runId: string) => {
      stop();
      try {
        const run = await api.status(apiKey, runId);
        if (run.status === "queued" || run.status === "running") {
          setState((s) => ({ ...s, run, busy: true }));
          timer.current = window.setTimeout(() => void follow(runId), POLL_MS);
          return;
        }
        const approval =
          run.status === "awaiting_approval" ? await api.approval(apiKey, runId) : null;
        const report = run.status === "completed" ? await api.report(apiKey, runId) : null;
        setState({ run, approval, report, busy: false, error: null });
      } catch (error) {
        setState((s) => ({ ...s, busy: false, error: message(error) }));
      }
    },
    [apiKey],
  );

  useEffect(() => stop, []);

  const start = async (incidentId: string) => {
    setState({ ...EMPTY, busy: true });
    try {
      const run = await api.analyze(apiKey, incidentId);
      await follow(run.run_id);
    } catch (error) {
      setState({ ...EMPTY, error: message(error) });
    }
  };

  const decide = async (approve: boolean, text: string) => {
    const runId = state.run?.run_id;
    if (!runId) return;
    setState((s) => ({ ...s, busy: true, error: null }));
    try {
      if (approve) await api.approve(apiKey, runId, text);
      else await api.reject(apiKey, runId, text);
      await follow(runId);
    } catch (error) {
      setState((s) => ({ ...s, busy: false, error: message(error) }));
    }
  };

  const reset = () => {
    stop();
    setState(EMPTY);
  };

  return { ...state, start, decide, reset };
}
