import React from 'react';
import * as m from 'motion/react-m';
import { ArrowDownToLine, Bluetooth, Cable, EthernetPort, Wifi } from 'lucide-react';
import { formatRate } from '../metrics.mjs';

const colors = ['var(--blue)', 'var(--mint)', 'var(--amber)', 'var(--violet)', '#e78eb0', '#91bf69', '#7acddc'];
const labels = { queued: 'Waiting', running: 'Downloading', saved: 'Saved', failed: 'Failed', paused: 'Paused', reconnecting: 'Reconnecting', cancelled: 'Cancelled', cancelling: 'Cancelling', recoverable: 'Saved progress', held: 'Held by Turbo' };
export const mib = bytes => (bytes / 1048576).toFixed(2) + ' MiB';

export function AdapterIcon({ name }) {
  const value = name.toLowerCase();
  const Icon = value.includes('bluetooth') ? Bluetooth : value.includes('wi-fi') ? Wifi
    : value.includes('usb') || value.includes('tether') ? Cable : EthernetPort;
  return <Icon size={18} aria-hidden />;
}

function BranchDiagram({ entries, connected, moving, reduce, orientation, turbo }) {
  const vertical = orientation === 'vertical';
  const junction = vertical ? [230, 116] : [330, 104];
  const destination = vertical ? [230, 164] : [411, 104];
  const icon = vertical ? [230, 183] : [430, 104];
  const tail = ' L' + destination.join(' ');
  return <svg className={'tree tree-' + orientation} viewBox={vertical ? '0 0 460 208' : '0 0 460 184'}
    role="img" aria-label={entries.length + ' connections merging into one file'}>
    <path className="trunk" d={'M' + junction.join(' ') + tail}/>
    {entries.map(([name], index) => {
      const spacing = (index - (entries.length - 1) / 2) * (vertical ? Math.min(94, 360 / (entries.length - 1)) : Math.min(43, 146 / (entries.length - 1)));
      const x = vertical ? 230 + spacing : 28;
      const y = vertical ? 25 : 104 + spacing;
      const path = vertical ? `M${x} ${y} C${x} 79 230 65 230 116`
        : `M${x} ${y} C171 ${y} 204 104 330 104`;
      const offline = !connected.has(name);
      const color = colors[index];
      return <g key={name}>
        <m.path d={path} fill="none" stroke={color} strokeWidth="2.5"
          initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1, opacity: offline ? .28 : .85 }}
          transition={{ duration: reduce ? 0 : .32 }}/>
        <circle cx={x} cy={y} r="7" fill="var(--panel)" stroke={color} strokeWidth="2" opacity={offline ? .4 : 1}/>
        {!reduce && !offline && moving.has(name) && [0, 1].map(packet => <circle className="packet" key={packet} r="3.5" fill={color}>
          <animateMotion dur={((turbo ? .7 : 1.7) + index * (turbo ? .1 : .22)) + 's'} begin={packet * .65 + 's'} repeatCount="indefinite" path={path + tail}/>
        </circle>)}
      </g>;
    })}
    <circle cx={junction[0]} cy={junction[1]} r="7" fill="var(--panel)" stroke="var(--accent)" strokeWidth="2"/>
    <g transform={'translate(' + icon.join(' ') + ')'}>
      <rect x="-19" y="-19" width="38" height="38" rx="10" fill="var(--tint)" stroke="var(--edge)"/>
      <path d="M0 -9V5m-5-5 5 5 5-5m-12 12h14" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </g>
  </svg>;
}

function DirectRoute({ name, connected, active, turbo }) {
  return <div className="direct-route" data-connected={connected}>
    <div className="route-source"><span className="route-icon"><AdapterIcon name={name}/></span>
      <div><strong>{name}</strong><small>{connected ? 'Direct connection' : 'Connection unavailable'}</small></div></div>
    <span className="route-wire" aria-hidden>{active && <span className={'route-pulse' + (turbo ? ' turbo-pulse' : '')}/>}</span>
    <span className="route-icon route-target" title="Destination file"><ArrowDownToLine size={18} aria-hidden/></span>
  </div>;
}

export function TransferTree({ entries, job, rows, reduce, orientation, speedUnit }) {
  const total = job ? Object.values(job.totals).reduce((sum, bytes) => sum + bytes, 0) : 0;
  const percent = job?.state === 'saved' ? 100 : job?.size ? Math.min(100, total / job.size * 100) : null;
  const checking = job?.state === 'running' && job.size != null && total >= job.size;
  const connected = new Set(rows.filter(row => row.status === 'Up').map(row => row.name));
  const moving = new Set(job?.state === 'running' ? job.active : []);
  const single = entries.length === 1;
  const name = entries[0]?.[0];
  return <section className={'tree-panel' + (job?.turbo ? ' turbo-tree' : '')} aria-labelledby="tree-title">
    <header className="section-head"><div><h2 id="tree-title">{single ? 'Transfer route' : 'Transfer tree'}</h2>
      <p>{single ? 'One connection to your file.' : 'See how your connections share a download.'}</p></div>
      <span className="pill">{checking ? 'Scanning file' : job ? labels[job.state] : entries.length ? 'Ready' : 'No connections'}</span></header>
    {single ? <DirectRoute name={name} connected={connected.has(name)} active={!reduce && connected.has(name) && moving.has(name)} turbo={Boolean(job?.turbo)}/>
      : entries.length ? <>
        <BranchDiagram entries={entries} connected={connected} moving={moving} reduce={reduce} orientation={orientation} turbo={Boolean(job?.turbo)}/>
        <ul className="legend">{entries.map(([adapter, bytes], index) =>
          <li key={adapter}><span className="swatch" style={{ background: colors[index] }}/><span>{adapter}</span>
            <small>{connected.has(adapter) ? (job ? mib(bytes) : 'Ready') : 'Unavailable'}</small></li>
        )}</ul>
      </> : <p className="route-empty">Select an available connection to see the route here.</p>}
    {job?.turbo && <p className="turbo-tree-note">Turbo is reserving available connections for this file.</p>}
    {job ? <div className="file">
      <div className="file-label"><span>{job.filename}</span><strong>{percent == null ? mib(total) : percent.toFixed(0) + '%'}</strong></div>
      <progress aria-label="File progress" max="100" value={percent ?? (job.state === 'running' ? undefined : 0)}/>
      {job.state === 'running' && !checking && <p className="transfer-rate">{formatRate(job.rate ?? 0, speedUnit)}</p>}
      {single && percent != null && <p>{mib(total)} received</p>}
      {job.error && <p className="error" role="alert">{job.error}</p>}
    </div> : entries.length > 0 && <p className="route-note">Transfer activity appears here once a download starts.</p>}
  </section>;
}
