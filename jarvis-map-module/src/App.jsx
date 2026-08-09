import React, { useEffect, useRef, useState, useCallback } from 'react';
import GlobeScene from './three/GlobeScene.js';
import HudCard from './components/HudCard.jsx';
import MemoryLog from './components/MemoryLog.jsx';
import QuickButtons from './components/QuickButtons.jsx';

const LOG_POOL = [
  { text: 'Memory Consolidation Started', status: 'run' },
  { text: 'Agent 7 Spawned · sandbox ready', status: 'run' },
  { text: 'Vector Index Rebuilt', status: 'ok' },
  { text: 'Threat Signature Updated', status: 'warn' },
  { text: 'Traffic Rerouted via Tokyo', status: 'ok' },
  { text: 'Model Hot-Reload Applied', status: 'ok' },
  { text: 'Data Sync → Singapore Node', status: 'run' },
  { text: 'Latency Optimized · -18ms', status: 'ok' },
  { text: 'Node Health Check Passed', status: 'ok' },
  { text: 'Anomaly Detected · Lagos', status: 'err' },
  { text: 'Voice Print Recalibrated', status: 'ok' },
  { text: 'Session Snapshot Archived', status: 'ok' },
];

const INITIAL_LOGS = [
  { text: 'User Analysis Completed', status: 'ok' },
  { text: 'Knowledge Graph Updated', status: 'ok' },
  { text: 'SQL Optimization Finished', status: 'ok' },
  { text: 'Agent Task Running', status: 'run' },
];

function nowTime() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export default function App() {
  const globeRef = useRef(null);
  const [embed] = useState(
    () => new URLSearchParams(window.location.search).has('embed'),
  );
  const [logs, setLogs] = useState(() =>
    INITIAL_LOGS.map((l) => ({ ...l, time: nowTime() })),
  );
  const [stats, setStats] = useState({
    nodes: 41, flow: '9.4', agents: 6, risk: 'LOW', uptime: 0,
  });
  const [clock, setClock] = useState(nowTime());

  // 嵌入模式（overlay WebView 内嵌）：透明背景、仅显示地图卡片
  useEffect(() => {
    if (embed) {
      document.body.classList.add('embed-mode');
      document.documentElement.classList.add('embed-mode');
      return () => {
        document.body.classList.remove('embed-mode');
        document.documentElement.classList.remove('embed-mode');
      };
    }
  }, [embed]);

  // 场景初始化
  useEffect(() => {
    let scene = null;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/data/countries.geojson');
        const countries = await res.json();
        if (cancelled || !globeRef.current) return;
        scene = new GlobeScene(globeRef.current, {
          textureUrl: '/textures/earth-dark.jpg',
          countries,
        });
      } catch (e) {
        console.error('[GlobeScene] init failed:', e);
      }
    })();
    return () => {
      cancelled = true;
      scene?.dispose();
    };
  }, []);

  const addLog = useCallback((text, status) => {
    setLogs((prev) => [{ text, status, time: nowTime() }, ...prev].slice(0, 40));
  }, []);

  // 实时刷新：时钟 / 态势数据 / 随机日志
  useEffect(() => {
    const t1 = setInterval(() => setClock(nowTime()), 1000);
    const t2 = setInterval(() => {
      setStats((s) => ({
        nodes: 41 + Math.floor(Math.random() * 5),
        flow: (8.2 + Math.random() * 4.6).toFixed(1),
        agents: 6 + (Math.random() > 0.7 ? 1 : 0),
        risk: ['LOW', 'LOW', 'MODERATE', 'MODERATE', 'ELEVATED'][Math.floor(Math.random() * 5)],
        uptime: s.uptime + 2,
      }));
    }, 2000);
    const t3 = setInterval(() => {
      const pick = LOG_POOL[Math.floor(Math.random() * LOG_POOL.length)];
      addLog(pick.text, pick.status);
    }, 5200);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
      clearInterval(t3);
    };
  }, [addLog]);

  const onQuickAction = (id) => {
    const map = {
      upload: ['Upload Initiated · 4.2 GB queued', 'run'],
      archive: ['Archive Snapshot Created', 'ok'],
      summary: ['Daily Summary Generated', 'ok'],
    };
    const [text, status] = map[id];
    addLog(text, status);
  };

  const uptimeStr = `${Math.floor(stats.uptime / 3600)}h ${Math.floor((stats.uptime % 3600) / 60)}m`;

  return (
    <div className="app">
      {!embed && (
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-logo">◆</span>
            <span className="topbar-title">J.A.R.V.I.S.</span>
            <span className="topbar-divider">//</span>
            <span className="topbar-sub">GLOBAL SITUATIONAL AWARENESS</span>
          </div>
          <div className="topbar-right">
            <span className="topbar-item">UPTIME {uptimeStr}</span>
            <span className="topbar-item topbar-clock">{clock}</span>
            <span className="topbar-item topbar-sec">SEC-7</span>
          </div>
        </header>
      )}

      {/* 右上角态势模块 */}
      <div className="module">
        {!embed && <QuickButtons onAction={onQuickAction} />}

        <HudCard title="GLOBAL SATCOM" subtitle="3D SITUATION MAP" className="globe-card">
          <div ref={globeRef} className="globe-canvas" />
          <div className="globe-stats">
            <div className="gstat">
              <span className="gstat-label">NODES</span>
              <span className="gstat-value">{stats.nodes}</span>
            </div>
            <div className="gstat">
              <span className="gstat-label">DATA FLOW</span>
              <span className="gstat-value">{stats.flow}<em>Gbps</em></span>
            </div>
            <div className="gstat">
              <span className="gstat-label">AGENTS</span>
              <span className="gstat-value">{stats.agents}</span>
            </div>
            <div className="gstat">
              <span className="gstat-label">RISK</span>
              <span className={`gstat-value risk-${stats.risk.toLowerCase()}`}>{stats.risk}</span>
            </div>
          </div>
        </HudCard>

        {!embed && <MemoryLog entries={logs} />}
      </div>
    </div>
  );
}
