// The Wizard's instrument: three rings for the three familiars (Seer, Scribe, Conjurer).
// On load the rings turn until their sigils line up on the meridian; a switched-off
// familiar's ring is dimmed, so the drawing also shows which agents are available.

import type { Specialist } from "@/lib/api";

type Ring = { agent: Specialist; r: number; color: string; sigil: string; from: string; ticks: number; major: number };

const RINGS: Ring[] = [
  { agent: "research", r: 104, color: "var(--research)", sigil: "☽", from: "-62deg", ticks: 72, major: 6 },
  { agent: "plan", r: 78, color: "var(--plan)", sigil: "☿", from: "48deg", ticks: 24, major: 3 },
  { agent: "execute", r: 52, color: "var(--execute)", sigil: "☉", from: "-34deg", ticks: 12, major: 3 },
];

const C = 120;

function tick(r: number, angleDeg: number, len: number) {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  const x1 = C + r * Math.cos(a);
  const y1 = C + r * Math.sin(a);
  const x2 = C + (r - len) * Math.cos(a);
  const y2 = C + (r - len) * Math.sin(a);
  return { x1: x1.toFixed(2), y1: y1.toFixed(2), x2: x2.toFixed(2), y2: y2.toFixed(2) };
}

export function Astrolabe({ enabled, className = "" }: { enabled: Record<Specialist, boolean>; className?: string }) {
  return (
    <svg viewBox="0 0 240 240" className={className} role="img" aria-label="An astrolabe with three rings: Seer, Scribe and Conjurer">
      {/* meridian the sigils align on */}
      <line x1={C} y1="4" x2={C} y2="236" stroke="var(--line)" strokeWidth="0.75" />
      <line x1="4" y1={C} x2="236" y2={C} stroke="var(--line)" strokeWidth="0.75" />

      {RINGS.map((ring) => {
        const on = enabled[ring.agent];
        return (
          <g key={ring.agent} className="ring" style={{ ["--from" as string]: ring.from, opacity: on ? 1 : 0.22 }}>
            <circle cx={C} cy={C} r={ring.r} fill="none" stroke={ring.color} strokeWidth="1.25" />
            <circle cx={C} cy={C} r={ring.r - 9} fill="none" stroke={ring.color} strokeWidth="0.5" opacity="0.6" />
            {Array.from({ length: ring.ticks }, (_, i) => {
              const angle = (360 / ring.ticks) * i;
              if (angle === 0) return null; // leave room for the sigil on the meridian
              const t = tick(ring.r, angle, i % ring.major === 0 ? 9 : 4);
              return <line key={i} {...t} stroke={ring.color} strokeWidth={i % ring.major === 0 ? 1 : 0.6} />;
            })}
            <circle cx={C} cy={C - ring.r + 4.5} r="8" fill="var(--fog)" stroke={ring.color} strokeWidth="1" />
            <text x={C} y={C - ring.r + 4.5} textAnchor="middle" dominantBaseline="central" fontSize="11" fill={ring.color}>
              {ring.sigil}
            </text>
          </g>
        );
      })}

      {/* the Wizard at the centre */}
      <circle cx={C} cy={C} r="20" fill="none" stroke="var(--ink)" strokeWidth="0.75" />
      <text x={C} y={C + 1} textAnchor="middle" dominantBaseline="central" fontSize="22" fill="var(--ink)">
        ✶
      </text>
    </svg>
  );
}
