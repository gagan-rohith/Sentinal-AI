import type { Incident } from "../api";

export function IncidentDetails({ incident }: { incident: Incident }) {
  const metrics = Object.entries(incident.metrics_summary);
  return (
    <section className="card">
      <h2>
        {incident.incident_id}: {incident.title}
      </h2>
      <p className="muted">
        {incident.service} in {incident.environment}, {incident.severity},{" "}
        {new Date(incident.timestamp).toLocaleString()}
      </p>
      <p>{incident.description}</p>
      {incident.symptoms.length > 0 && (
        <>
          <h3>Symptoms</h3>
          <ul>
            {incident.symptoms.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </>
      )}
      {metrics.length > 0 && (
        <>
          <h3>Metrics at alert time</h3>
          <dl className="metrics">
            {metrics.map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}
