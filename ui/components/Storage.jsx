import React from 'react';
import { HardDrive } from 'lucide-react';
import { formatStorage } from '../metrics.mjs';

export function Storage({ drives, updated }) {
  return <section className="surface storage-panel" aria-labelledby="storage-title">
    <header className="section-head"><div><h2 id="storage-title">Storage</h2><p>Local drive usage</p></div></header>
    {drives.length ? <ul className="storage-list">{drives.map(({ drive, total, free }) => {
      const used = Math.max(0, Math.min(total, total - free));
      return <li key={drive}>
        <div className="storage-drive"><HardDrive size={17} aria-hidden/><strong>Drive {drive}</strong>
          <span>{Math.round(used / total * 100)}% used</span></div>
        <meter aria-label={'Space used on drive ' + drive} min={0} max={total} value={used}/>
        <div className="storage-caption"><span>{formatStorage(used)} used</span><span>{formatStorage(free)} free</span></div>
        <small>{formatStorage(total)} total</small>
      </li>;
    })}</ul> : <p>{updated ? 'No local drive readings are available.' : 'Reading local drives…'}</p>}
    {updated && <p className="storage-updated">Updated at {updated}</p>}
  </section>;
}
