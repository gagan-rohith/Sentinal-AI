import { useEffect, useState } from "react";

import { api, ApiError, type Incident, type RunRecord } from "./api";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { IncidentDetails } from "./components/IncidentDetails";
import { IncidentList } from "./components/IncidentList";
import { ReportView } from "./components/ReportView";
import { StagePipeline } from "./components/StagePipeline";
import { useRun } from "./useRun";
import { Overview } from "./views/Overview";

const KEY_STORAGE = "sentinel.apiKey";

type View = "overview" | "incidents";

// sessionStorage is cleared when the tab closes; the key never goes to localStorage.
function readKey(): string {
  try {
    return window.sessionStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

function saveKey(key: string) {
  try {
    window.sessionStorage.setItem(KEY_STORAGE, key);
  } catch {
    // Storage can be unavailable (private mode); the key then lasts for this page only.
  }
}

export function App() {
  const [apiKey, setApiKey] = useState(readKey);
  const [draftKey, setDraftKey] = useState("");
  const [editingKey, setEditingKey] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [health, setHealth] = useState<string>("checking");
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const run = useRun(apiKey);

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth(h.status))
      .catch(() => setHealth("unreachable"));
  }, []);

  useEffect(() => {
    if (!apiKey) return;
    api
      .incidents(apiKey)
      .then((list) => {
        setIncidents(list);
        setLoadError(null);
        setSelectedId((current) => current ?? list.find((i) => i.status === "open")?.incident_id ?? null);
      })
      .catch((error: unknown) =>
        setLoadError(error instanceof ApiError ? `${error.status}: ${error.message}` : String(error)),
      );
  }, [apiKey]);

  const selected = incidents.find((i) => i.incident_id === selectedId) ?? null;

  const applyKey = () => {
    saveKey(draftKey.trim());
    setApiKey(draftKey.trim());
    setDraftKey("");
    setEditingKey(false);
  };

  const openRun = (record: RunRecord) => {
    setView("incidents");
    setSelectedId(record.incident_id);
    void run.open(record.run_id);
  };

  const healthTone = health === "ok" ? "good" : health === "checking" ? "neutral" : "critical";

  return (
    <div className="app">
      <header className="appbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          SentinelAI
        </div>
        <nav className="tabs" aria-label="Sections">
          {(["overview", "incidents"] as const).map((name) => (
            <button
              key={name}
              type="button"
              className={view === name ? "tab active" : "tab"}
              aria-current={view === name ? "page" : undefined}
              onClick={() => setView(name)}
            >
              {name === "overview" ? "Overview" : "Incidents"}
            </button>
          ))}
        </nav>
        <span className={`status tone-${healthTone}`} title="API health">
          API {health}
        </span>
        {apiKey && !editingKey ? (
          <button type="button" className="secondary small" onClick={() => setEditingKey(true)}>
            Change key
          </button>
        ) : (
          <form
            className="key-form"
            onSubmit={(e) => {
              e.preventDefault();
              applyKey();
            }}
          >
            <input
              type="password"
              placeholder="Paste an API key"
              aria-label="API key"
              value={draftKey}
              onChange={(e) => setDraftKey(e.target.value)}
              autoComplete="off"
            />
            <button type="submit" disabled={!draftKey.trim()}>
              Use key
            </button>
          </form>
        )}
      </header>

      <main className="page">
        {!apiKey && (
          <p className="callout">
            Paste an operator key to analyze incidents, or an admin key to also approve actions.
            Generate one with <code>python -m auth.api_keys operator</code>.
          </p>
        )}
        {loadError && <p className="callout tone-critical">{loadError}</p>}

        {view === "overview" ? (
          <Overview apiKey={apiKey} health={health} incidents={incidents} onOpenRun={openRun} />
        ) : (
          <div className="workspace">
            <IncidentList
              incidents={incidents}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                run.reset();
              }}
            />
            <div className="content">
              {selected ? (
                <>
                  <IncidentDetails incident={selected} />
                  <div className="actions">
                    <button
                      type="button"
                      disabled={run.busy || !apiKey}
                      onClick={() => void run.start(selected.incident_id)}
                    >
                      {run.run ? "Analyze again" : "Analyze incident"}
                    </button>
                    {run.busy && <span className="muted small">Agents are working...</span>}
                  </div>
                  {run.run && <StagePipeline run={run.run} />}
                  {run.error && <p className="callout tone-critical">{run.error}</p>}
                  {run.run?.status === "failed" && (
                    <p className="callout tone-critical">
                      Run failed: {run.run.error_code}: {run.run.error_message}
                    </p>
                  )}
                  {run.approval && run.run?.status === "awaiting_approval" && (
                    <ApprovalPanel approval={run.approval} busy={run.busy} onDecide={run.decide} />
                  )}
                  {run.report && <ReportView report={run.report} />}
                </>
              ) : (
                <p className="muted">Select an incident.</p>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
