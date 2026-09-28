import { useState, type ReactNode } from "react";

import type { RunStatus } from "../api";
import { percent, RUN_STATUS } from "../format";

const TONE_ICON: Record<string, string> = {
  good: "✓",
  warning: "!",
  critical: "×",
  info: "●",
  neutral: "○",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const { label, tone } = RUN_STATUS[status];
  return (
    <span className={`status tone-${tone}`}>
      <span aria-hidden="true">{TONE_ICON[tone]}</span> {label}
    </span>
  );
}

export function Tag({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span className={`tag${tone ? ` tone-${tone}` : ""}`}>{children}</span>;
}

export function StatTile({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: string;
}) {
  return (
    <div className={`stat-tile${tone ? ` tone-${tone}` : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

// A confidence or share, drawn as a track with a filled portion and a visible number.
export function Meter({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <span className="meter" role="img" aria-label={`${label ?? "value"} ${percent(clamped)}`}>
      <span className="meter-track">
        <span className="meter-fill" style={{ width: `${clamped * 100}%` }} />
      </span>
      <span className="meter-value">{percent(clamped)}</span>
    </span>
  );
}

export interface Bar {
  label: string;
  value: number;
  display: string;
  emphasis?: boolean;
  note?: string;
}

// Horizontal bars for one measure. One bar carries the accent (the point of the chart),
// the rest are neutral context. Every bar has a direct value label and a hover tooltip.
export function BarList({ bars, max, caption }: { bars: Bar[]; max: number; caption: string }) {
  const [hovered, setHovered] = useState<string | null>(null);
  return (
    <figure className="bar-list">
      <figcaption>{caption}</figcaption>
      {bars.map((bar) => (
        <div
          key={bar.label}
          className="bar-row"
          onMouseEnter={() => setHovered(bar.label)}
          onMouseLeave={() => setHovered(null)}
          onFocus={() => setHovered(bar.label)}
          onBlur={() => setHovered(null)}
          tabIndex={0}
        >
          <span className="bar-label">{bar.label}</span>
          <span className="bar-track">
            <span
              className={`bar-fill${bar.emphasis ? " emphasis" : ""}`}
              style={{ width: `${Math.max((bar.value / max) * 100, 1)}%` }}
            />
            {hovered === bar.label && (
              <span className="bar-tooltip" role="tooltip">
                <strong>{bar.label}</strong> {bar.display}
                {bar.note && <span className="muted"> {bar.note}</span>}
              </span>
            )}
          </span>
          <span className="bar-value">{bar.display}</span>
        </div>
      ))}
    </figure>
  );
}

export function EvidenceChip({ id, summary }: { id: string; summary?: string }) {
  return (
    <abbr className="chip" title={summary ?? "evidence not found"}>
      {id}
    </abbr>
  );
}
