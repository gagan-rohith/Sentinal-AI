import type { Incident } from "../api";
import { dateTime } from "../format";
import { SEVERITY_TONE } from "./IncidentList";
import { Tag } from "./ui";

export function IncidentDetails({ incident }: { incident: Incident }) {
  const metrics = Object.entries(incident.metrics_summary);
  return (
    <section className="card incident-details">
      <div className="eyebrow">
        {incident.incident_id} <Tag tone={SEVERITY_TONE[incident.severity]}>{incident.severity}</Tag>
        <Tag>{incident.status}</Tag>
      </div>
      <h2 className="incident-title">{incident.title}</h2>
      <p className="muted small">
        {incident.service} in {incident.environment}, alerted {dateTime(incident.timestamp)}
      </p>
      <p>{incident.description}</p>
      {incident.symptoms.length > 0 && (
        <>
          <h3>Symptoms</h3>
          <div className="chips">
            {incident.symptoms.map((s) => (
              <span key={s} className="symptom">
                {s}
              </span>
            ))}
          </div>
        </>
      )}
      {metrics.length > 0 && (
        <>
          <h3>Metrics at alert time</h3>
          <dl className="metrics">
            {metrics.map(([name, value]) => (
              <div key={name}>
                <dt>{name.replaceAll("_", " ")}</dt>
                <dd>{value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}
