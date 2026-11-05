import React, { useId } from 'react';
import { Activity, ArrowUp } from 'lucide-react';
import { AdapterIcon } from './TransferTree';
import { formatRate } from '../metrics.mjs';

export function adapterRate(row, direction = 'rx') {
  const value = row[direction + 'Rate'];
  return Number.isFinite(value) ? Math.max(0, value * 125000) : null;
}

export function totalRate(rows, direction = 'rx') {
  const values = rows.map(row => adapterRate(row, direction)).filter(value => value !== null);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function displayCeiling(bytes) {
  const mbps = (bytes ?? 0) * 8 / 1_000_000;
  return ([10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000].find(limit => limit >= mbps * 1.12) ?? Math.ceil(mbps / 10000) * 10000) * 125000;
}

export function SpeedDial({ value, unit, label, compact = false, color = 'blue', turbo = false, reduce = false }) {
  const id = useId().replaceAll(':', '');
  const limit = displayCeiling(value);
  const fraction = Math.min(1, Math.max(0, (value ?? 0) / limit));
  const formatted = formatRate(value, unit);
  const [amount, suffix] = formatted.split(' ');
  const ticks = [0, 1, 2, 3, 4, 5, 6].map(index => {
    const angle = Math.PI + index * Math.PI / 6;
    return { x1: 120 + Math.cos(angle) * 83, y1: 126 + Math.sin(angle) * 83,
      x2: 120 + Math.cos(angle) * 76, y2: 126 + Math.sin(angle) * 76 };
  });
  return <div className={'speed-dial' + (compact ? ' compact-dial' : '') + (turbo ? ' turbo-dial' : '')}
    data-color={color} title={'Display scale: 0 to ' + formatRate(limit, unit)} aria-label={label + ': ' + formatted + '. Display scale: 0 to ' + formatRate(limit, unit)}>
    <svg viewBox="0 0 240 155" aria-hidden="true">
      <defs><linearGradient id={id} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stopColor="var(--gauge-start)"/><stop offset="100%" stopColor="var(--gauge-end)"/>
      </linearGradient></defs>
      <path className="dial-track" d="M24 126 A96 96 0 0 1 216 126"/>
      <path className="dial-value" pathLength="100" stroke={'url(#' + id + ')'}
        d="M24 126 A96 96 0 0 1 216 126" strokeDasharray="100 100"
        style={{ strokeDashoffset: 100 - fraction * 100, transitionDuration: reduce ? '0s' : '.55s' }}/>
      {!compact && <g className="dial-ticks">{ticks.map((tick, index) => <line key={index} {...tick}/>)}</g>}
      {!compact && <><text className="dial-number" x="120" y="99">{amount}</text>
        <text className="dial-unit" x="120" y="121">{suffix || 'Awaiting sample'}</text></>}
    </svg>
    {!compact && <div className="dial-scale"><span>0</span><span>{formatRate(limit, unit)}</span></div>}
  </div>;
}

export function SpeedSummary({ rows, unit, turbo, reduce, updated, networkError }) {
  const receive = totalRate(rows);
  const send = totalRate(rows, 'tx');
  return <section className={'surface speed-summary' + (turbo ? ' turbo-surface' : '')} aria-labelledby="speed-heading">
    <header className="section-head"><div><h2 id="speed-heading">Network speed</h2><p>Aggregate receive · all apps</p></div>
      <span className="live-indicator"><Activity size={13} aria-hidden/>{networkError ? 'Stale' : updated ? 'Live' : 'Reading'}</span></header>
    <SpeedDial value={receive} unit={unit} label="Total receive speed" turbo={turbo} reduce={reduce}/>
    <div className="speed-summary-footer"><span><ArrowUp size={13} aria-hidden/> Send <strong>{formatRate(send, unit)}</strong></span>
      <span>{rows.length} {rows.length === 1 ? 'connection' : 'connections'}</span></div>
  </section>;
}

export function ConnectionSpeeds({ rows, unit, turbo, reduce, limit = null }) {
  const visible = limit === null ? rows : rows.slice(0, limit);
  return <div className="connection-speeds">{visible.map((row, index) => {
    const receive = adapterRate(row);
    return <section className={'connection-speed' + (turbo ? ' turbo-connection' : '')} key={row.index}>
      <span className="connection-symbol" data-color={index % 2 ? 'mint' : 'blue'}><AdapterIcon name={row.kind || row.name}/></span>
      <div className="connection-description"><strong>{row.kind || row.name}</strong><small>{row.kind ? row.name : row.link}</small></div>
      <div className="connection-numbers"><strong>{formatRate(receive, unit)}</strong>
        <small><ArrowUp size={11} aria-hidden/>{formatRate(adapterRate(row, 'tx'), unit)}</small></div>
      <SpeedDial compact value={receive} unit={unit} label={row.name + ' receive speed'} color={index % 2 ? 'mint' : 'blue'} turbo={turbo} reduce={reduce}/>
    </section>;
  })}</div>;
}
