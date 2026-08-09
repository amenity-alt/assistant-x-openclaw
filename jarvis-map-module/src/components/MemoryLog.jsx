import React from 'react';
import HudCard from './HudCard.jsx';

const STATUS_META = {
  ok: { dot: '#3dff8a', icon: '✓', label: 'OK' },
  run: { dot: '#35d0ff', icon: '⟳', label: 'RUN' },
  warn: { dot: '#ffb347', icon: '⚠', label: 'WARN' },
  err: { dot: '#ff5a6e', icon: '✕', label: 'ERR' },
};

/** Memory Log · Jarvis 记忆中心 */
export default function MemoryLog({ entries }) {
  return (
    <HudCard title="MEMORY LOG" subtitle="jarvis://core/mem" className="memory-log">
      <div className="mem-list">
        {entries.map((e, i) => {
          const m = STATUS_META[e.status] || STATUS_META.ok;
          return (
            <div key={`${e.time}-${i}`} className="mem-row">
              <span className="mem-dot" style={{ background: m.dot, boxShadow: `0 0 8px ${m.dot}` }} />
              <span className="mem-icon" style={{ color: m.dot }}>{m.icon}</span>
              <span className="mem-text">{e.text}</span>
              <span className="mem-time">{e.time}</span>
            </div>
          );
        })}
        {entries.length === 0 && <div className="mem-empty">— NO RECORDS —</div>}
      </div>
      <div className="mem-footer">
        <span>RECORDS {String(entries.length).padStart(3, '0')}</span>
        <span className="mem-footer-live">● LIVE</span>
      </div>
    </HudCard>
  );
}
