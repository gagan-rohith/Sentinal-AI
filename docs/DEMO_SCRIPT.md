# Demo script

A shot list for a 2 to 3 minute video of the INC-1060 scenario, and the same flow for a live
screen share. Everything shown runs locally; no hosted service or API spend is involved.

## The scenario

`checkout-api` starts returning 5xx after a flash sale drives traffic to about 2.5x normal.
There is also a deploy three hours earlier, which is the obvious suspect. The agents have to:

- find that the PostgreSQL connection pool is exhausted (pool at 100/100, 412 requests waiting),
- rule out the deploy because errors did not start within 30 minutes of it,
- propose a rolling restart, which changes production and so waits for a human,
- refuse the approval from an operator, accept it from an admin, execute, and write the postmortem.

## Before recording

1. Start Docker Desktop, then the stack with the web UI:

   ```bash
   docker compose --profile frontend up --build -d
   ```

   Wait until `docker compose ps` shows the api as healthy. The UI is on http://localhost:3000.
2. Have two keys ready, an operator key and an admin key, both configured in `.env`
   (`python -m auth.api_keys operator`, `python -m auth.api_keys admin`). Keep them in a
   password manager or a file that is not on screen.
3. Refresh the benchmark if the code changed since the last run: `make bench`
   (or `python -m evals.benchmark`). The overview reads `evals/reports/latest.json`.
4. Browser: 1920x1080, zoom 110 to 125%, bookmarks bar hidden, notifications off.
5. For the MCP segment, connect Claude Desktop as described in [MCP.md](MCP.md) with an
   **operator** key, and check the SentinelAI tools show up in the tools menu.
6. Never show `.env`, the terminal where keys were generated, or a key in plain text. The
   key field in the UI is a password field; paste, do not type.

## Shot list

Times are targets for a 2:45 cut. The voiceover lines are suggestions; say them your way.

### 0:00 to 0:15, the problem

Screen: the Overview tab.

> When an alert fires, an on-call engineer spends the first twenty minutes pulling logs,
> metrics, deploy history and runbooks together. SentinelAI does that with a team of
> agents, shows its evidence, and never touches production without a human.

### 0:15 to 0:35, overview

Screen: stay on Overview. Point at the tiles, the recent runs table and the benchmark panel.

> This is the overview: open incidents, runs waiting for a decision, and the latest
> benchmark. Hybrid search beats keyword and vector search alone on runbook retrieval.

### 0:35 to 1:00, start the analysis

1. Paste the **operator** key with Change key.
2. Open the Incidents tab, pick INC-1060, and show the symptoms and metrics.
3. Click Analyze incident. The stepper moves through triage, context, retrieval, root cause,
   remediation and critic, then stops at Approval.

> Triage classifies it as a database problem. Context collection pulls health, logs,
> metrics and deployments. Retrieval searches runbooks and past incidents in Elasticsearch.
> A critic checks every claim against the evidence before anything reaches a human.

### 1:00 to 1:25, the approval gate

1. Show the approval panel: root cause, confidence, the proposed `restart_service` call,
   its risk and the rollback plan.
2. Click Approve and execute while still on the operator key. The page shows
   `403 forbidden: role 'operator' is missing permission 'remediation:execute'`.
3. Change key to the **admin** key, add a comment, approve.

> The plan includes a production change, so the run pauses. An operator cannot approve it.
> An admin can, and the approval is single use.

### 1:25 to 2:00, the report

Scroll through the report once, slowly:

1. Root cause and confidence at the top.
2. What happened: the timeline puts the deploy, the traffic change, the first error, the
   alert, the approval and the restart in order.
3. Hypotheses considered: pool exhaustion is selected; the deploy regression is marked
   Ruled out. Hover an evidence chip to show what E12 refers to.
4. Decision: the steps, the approval with its comment, and the executed restart.

> Every hypothesis cites evidence ids, and the critic rejects ids that do not exist. The
> recent deploy looked guilty, but the errors started three hours later, so it is ruled out.

### 2:00 to 2:30, MCP in Claude Desktop

1. In Claude Desktop, paste:

   > checkout-api is throwing 503s. Check its health, logs and recent deployments at
   > 2026-04-30T08:47:00Z, find the matching runbook and similar past incidents, and tell
   > me the most likely root cause.

   Let it call `get_service_health`, `search_logs`, `get_deployment_status`,
   `search_runbooks` and `search_incidents`.
2. Then ask: "Restart checkout-api." Either Claude explains that the tool needs an approved
   `approval_id` it does not have, or it calls the tool and the server refuses it: the
   operator key lacks the admin role, and even an admin needs an approval from the workflow.
   Record whichever happens; do not script the exact error text.

> The same tools are exposed over MCP, behind the same permission checks. An assistant can
> investigate freely but cannot change production on its own.

If Claude Desktop is not set up, cut this segment; the terminal demo below covers the same
refusal.

### 2:30 to 2:45, honesty and close

Screen: back to the benchmark panel, then `evals/reports/latest.md` or the GitHub Actions page.

> On incident types it has seen, it picks the right runbook every time. On types held out
> of the index it drops to about 42 percent, and I report that number too. These results
> are from the deterministic agent mode; the Claude-backed mode is wired in but has not
> been benchmarked. It runs in Docker, with Kubernetes manifests, Terraform and CI in the repo.

Read the numbers off the current report before recording; do not reuse the ones above if
the benchmark has been rerun.

## Terminal version

For a screen share without the UI, or as B-roll, the same story runs in a terminal:

```bash
make demo                     # uses Elasticsearch, as configured in .env
make demo ARGS=--memory       # no Docker needed
make demo ARGS="--pause 2"    # two second pause between sections, for recording
```

Without `make` (for example on Windows): `python -m app.demo --pause 2`.

It starts the API in-process with throwaway operator and admin keys and a temporary
database, so it does not need your keys and leaves `var/sentinel.db` untouched. It prints
the incident, the approval request, the refused operator approval, the admin approval, a
refused second approval, then the agent calls, triage, evidence, hypotheses (with the
deploy ruled out), the remediation plan, the executed restart and the postmortem. It exits
non-zero if any step does not behave as described.

## If something goes wrong on camera

| Symptom | Fix |
|---|---|
| UI shows 401 | Wrong or stale key; paste it again with Change key |
| Run stays on Running after approval | The api image is out of date: `docker compose build api ingest`, then `up -d` again |
| Health shows search unavailable | Elasticsearch is still starting; wait for `docker compose ps` to show it healthy |
| Overview says no benchmark report | Run `make bench` |
| `make demo` says search is not available | Start Elasticsearch, or use `ARGS=--memory` |
