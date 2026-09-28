import { useMemo, useState } from "react";

import type { Incident } from "../api";
import { Tag } from "./ui";

interface Props {
  incidents: Incident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export const SEVERITY_TONE: Record<string, string> = {
  sev1: "critical",
  sev2: "serious",
  sev3: "warning",
  sev4: "neutral",
};

export function IncidentList({ incidents, selectedId, onSelect }: Props) {
  const [filter, setFilter] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return incidents.filter(
      (i) =>
        (!openOnly || i.status === "open") &&
        (!needle ||
          [i.incident_id, i.title, i.service].some((v) => v.toLowerCase().includes(needle))),
    );
  }, [incidents, filter, openOnly]);

  return (
    <aside className="card incident-list" aria-label="Incidents">
      <input
        type="search"
        placeholder="Filter by id, title or service"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <label className="check">
        <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
        Open only
      </label>
      <p className="muted small">
        {shown.length} of {incidents.length}
      </p>
      <ul>
        {shown.map((incident) => (
          <li key={incident.incident_id}>
            <button
              type="button"
              className={`incident-item${incident.incident_id === selectedId ? " selected" : ""}`}
              aria-current={incident.incident_id === selectedId}
              onClick={() => onSelect(incident.incident_id)}
            >
              <span className="row">
                <strong>{incident.incident_id}</strong>
                <Tag tone={SEVERITY_TONE[incident.severity]}>{incident.severity}</Tag>
                {incident.status === "open" && <Tag tone="info">open</Tag>}
              </span>
              <span className="item-title">{incident.title}</span>
              <span className="muted small">{incident.service}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
