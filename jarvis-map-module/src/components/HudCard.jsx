import React from 'react';

/** 悬浮玻璃 HUD 卡片：标题栏 + 四角亮角 + 扫描线 */
export default function HudCard({ title, subtitle, children, className = '' }) {
  return (
    <div className={`hud-panel ${className}`}>
      <div className="hud-corner tl" />
      <div className="hud-corner tr" />
      <div className="hud-corner bl" />
      <div className="hud-corner br" />
      <div className="hud-panel-head">
        <span className="hud-status-dot" />
        <span className="hud-title">{title}</span>
        {subtitle && <span className="hud-subtitle">{subtitle}</span>}
      </div>
      <div className="hud-panel-body">{children}</div>
      <div className="hud-scanline" />
    </div>
  );
}
