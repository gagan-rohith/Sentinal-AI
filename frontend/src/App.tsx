import { useEffect, useState } from "react";

import { api, ApiError, type Incident } from "./api";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { IncidentDetails } from "./components/IncidentDetails";
import { IncidentList } from "./components/IncidentList";
import { ReportView } from "./components/ReportView";
import { StagePipeline } from "./components/StagePipeline";
import { useRun } from "./useRun";

const KEY_STORAGE = "sentinel.apiKey";

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
  };

  return (
    <div className="app">
      <header>
        <h1>SentinelAI</h1>
        <span className={`health ${health}`}>API {health}</span>
        <form
          className="key-form"
          onSubmit={(e) => {
            e.preventDefault();
            applyKey();
          }}
        >
          <input
            type="password"
            placeholder={apiKey ? "API key set; paste another to switch" : "Paste an API key"}
            value={draftKey}
            onChange={(e) => setDraftKey(e.target.value)}
            autoComplete="off"
          />
          <button type="submit" disabled={!draftKey.trim()}>
            Use key
          </button>
        </form>
      </header>

      {!apiKey && (
        <p className="notice">
          Paste an operator key to analyze incidents, or an admin key to also approve actions.
          Generate one with <code>python -m auth.api_keys operator</code>.
        </p>
      )}
      {loadError && <p className="error">{loadError}</p>}

      <main>
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
              </div>
              {run.run && <StagePipeline run={run.run} />}
              {run.error && <p className="error">{run.error}</p>}
              {run.run?.status === "failed" && (
                <p className="error">
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
      </main>
    </div>
  );
}
