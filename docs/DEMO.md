# Demo

How to run the INC-1060 scenario end to end, in the web UI or in a terminal. Everything runs
locally in heuristic mode; no hosted service or API key for an LLM is needed.

## The scenario

`checkout-api` starts returning 5xx after a flash sale drives traffic to about 2.5x normal.
There is also a deploy three hours earlier, which is the obvious suspect. The agents have to:

- find that the PostgreSQL connection pool is exhausted (pool at 100/100, 412 requests waiting),
- rule out the deploy because errors did not start within 30 minutes of it,
- propose a rolling restart, which changes production and so waits for a human,
- refuse the approval from an operator, accept it from an admin, execute, and write the
  postmortem.

## Live replay site

https://gagan-rohith.github.io/sentinel-ai/ is the same web UI built in replay mode. Every
incident has a recorded run; runs that pause for approval were recorded twice, approved and
rejected, so either decision plays back what the system actually did. The role switch at the
top stands in for API keys, and the role rules match the API: approving as an operator returns
the same 403.

To refresh the recordings after changing the agents (Elasticsearch running, as for the
benchmark):

```bash
make record-demo        # writes frontend/public/demo
```

Commit the result; the `pages` workflow rebuilds the site on every push to `main` that
touches `frontend/`. To preview locally:

```bash
cd frontend
VITE_DEMO=1 npm run dev
```

## In the web UI

1. Start Docker Desktop, then the stack with the web UI:

   ```bash
   docker compose --profile frontend up --build -d
   ```

   Wait until `docker compose ps` shows the api as healthy, then open http://localhost:3000.
2. You need an operator key and an admin key configured in `.env`
   (`python -m auth.api_keys operator`, `python -m auth.api_keys admin`; see the
   [README](../README.md#quick-start)).
3. Paste the operator key, open the Incidents tab, pick INC-1060 and click Analyze incident.
   The stepper moves through triage, context, retrieval, root cause, remediation and critic,
   then stops at Approval.
4. The approval panel shows the root cause, its confidence, the proposed
   `restart_service(service=checkout-api)` call, its risk and the rollback plan. Approving with
   the operator key is refused:
   `403 forbidden: role 'operator' is missing permission 'remediation:execute'`.
5. Switch to the admin key with Change key, add a comment and approve. The restart runs once
   and the report appears:
   - the root cause and its confidence,
   - what happened, with a timeline of the deploy, the traffic change, the first error, the
     alert, the approval and the restart,
   - the evidence gathered, grouped by kind,
   - the hypotheses considered, with pool exhaustion selected and the deploy regression ruled
     out (hover an evidence chip to see what it refers to),
   - the decision: remediation steps, the approval and the executed action,
   - follow-up items and the critic's verdict.

The Overview tab shows open incidents, runs waiting for a decision, recent runs and the latest
benchmark from `evals/reports/latest.json` (refresh it with `make bench`).

## In a terminal

The same story runs as a script against the real HTTP API:

```bash
make demo                     # uses Elasticsearch, as configured in .env
make demo ARGS=--memory       # in-memory search, no Docker needed
make demo ARGS="--pause 2"    # two second pause between sections
```

Without `make` (for example on Windows): `python -m app.demo --memory`.

It starts the API in-process with throwaway operator and admin keys and a temporary database,
so it does not need your keys and leaves `var/sentinel.db` untouched. It prints the incident,
the approval request, the refused operator approval, the admin approval, a refused second
approval, then the agent calls, triage, evidence, hypotheses (with the deploy ruled out), the
remediation plan, the executed restart and the postmortem. It exits non-zero if any step does
not behave as described, so it also works as a smoke test.

## From Claude Desktop over MCP

With the MCP server connected as described in [MCP.md](MCP.md), using an operator key, try:

> checkout-api is throwing 503s. Check its health, logs and recent deployments at
> 2026-04-30T08:47:00Z, find the matching runbook and similar past incidents, and tell me the
> most likely root cause.

Claude can call the read-only tools freely. Asking it to restart `checkout-api` is refused:
the operator key lacks the admin role, and even an admin needs an approval id from the
approval workflow.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows 401 | Wrong or stale key; paste it again with Change key |
| Run stays on Running after approval | The api image is out of date: `docker compose build api ingest`, then `up -d` again |
| Health shows search unavailable | Elasticsearch is still starting; wait for `docker compose ps` to show it healthy |
| Overview says no benchmark report | Run `make bench` |
| `make demo` says search is not available | Start Elasticsearch, or use `ARGS=--memory` |
