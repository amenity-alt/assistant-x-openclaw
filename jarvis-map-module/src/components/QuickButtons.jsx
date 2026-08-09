import React, { useState } from 'react';

const BUTTONS = [
  { id: 'upload', label: 'UPLOAD', icon: '⇧' },
  { id: 'archive', label: 'ARCHIVE', icon: '▣' },
  { id: 'summary', label: 'SUMMARY', icon: '∑' },
];

/** 左侧快捷按钮：半透明玻璃 + 蓝色发光边框 */
export default function QuickButtons({ onAction }) {
  const [active, setActive] = useState(null);

  const handle = (id) => {
    setActive(id);
    onAction?.(id);
    setTimeout(() => setActive(null), 450);
  };

  return (
    <div className="quick-buttons">
      {BUTTONS.map((b) => (
        <button
          key={b.id}
          type="button"
          className={`qbtn ${active === b.id ? 'qbtn-active' : ''}`}
          onClick={() => handle(b.id)}
        >
          <span className="qbtn-icon">{b.icon}</span>
          <span className="qbtn-label">{b.label}</span>
        </button>
      ))}
    </div>
  );
}
