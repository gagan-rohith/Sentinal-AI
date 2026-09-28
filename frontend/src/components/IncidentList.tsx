import { useMemo, useState } from "react";

import type { Incident } from "../api";

interface Props {
  incidents: Incident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function IncidentList({ incidents, selectedId, onSelect }: Props) {
  const [filter, setFilter] = useState("");
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return incidents.filter(
      (i) =>
        !needle ||
        [i.incident_id, i.title, i.service].some((v) => v.toLowerCase().includes(needle)),
    );
  }, [incidents, filter]);

  return (
    <aside className="incident-list">
      <input
        type="search"
        placeholder="Filter by id, title or service"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <ul>
        {shown.map((incident) => (
          <li key={incident.incident_id}>
            <button
              type="button"
              className={incident.incident_id === selectedId ? "selected" : ""}
              onClick={() => onSelect(incident.incident_id)}
            >
              <span className="row">
                <strong>{incident.incident_id}</strong>
                <span className={`badge ${incident.severity}`}>{incident.severity}</span>
                {incident.status === "open" && <span className="badge open">open</span>}
              </span>
              <span className="muted">{incident.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
