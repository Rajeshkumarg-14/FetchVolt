import React from 'react';
import { Download, Pause, Play, X, Zap } from 'lucide-react';
import { Dropdown } from './Dropdown';
import { formatRate } from '../metrics.mjs';
import { mib } from './TransferTree';

export const jobLabels = { queued: 'Waiting', running: 'Downloading', saved: 'Saved', failed: 'Failed', paused: 'Paused',
  reconnecting: 'Reconnecting', cancelled: 'Cancelled', cancelling: 'Cancelling', recoverable: 'Saved progress', held: 'Held by Turbo' };
const priorities = ['high', 'normal', 'low'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) }));

export function TransferQueue({ jobs, selected, select, apiReady, chosen, speedUnit, control, resume, updateQueue, turbo }) {
  const active = jobs.filter(job => ['running', 'paused', 'reconnecting', 'held', 'cancelling'].includes(job.state)).length;
  const waiting = jobs.filter(job => job.state === 'queued').length;
  return <section className="surface queue"><header className="section-head"><div><h2>Transfer queue</h2>
    <p>{active} active <span aria-hidden>·</span> {waiting} waiting</p></div><span className="queue-priority-note">Priority order</span></header>
    {jobs.length ? <ul className="jobs">{[...jobs].reverse().map(job => {
      const complete = Object.values(job.totals).reduce((sum, count) => sum + count, 0);
      const percent = job.size ? Math.min(100, complete / job.size * 100) : null;
      const canControl = ['running', 'paused', 'reconnecting', 'held'].includes(job.state);
      const recoverable = ['recoverable', 'failed'].includes(job.state);
      return <li key={job.id} data-selected={selected === job.id}>
        <span className="queue-file-icon"><Download size={16} aria-hidden/></span>
        <button className="job-select" type="button" aria-pressed={selected === job.id} onClick={() => select(job.id)}>
          <strong>{job.filename}</strong>
          <small>{jobLabels[job.state] || job.state}{job.state === 'recoverable' ? ' · verify on resume' : ''}
            {job.state === 'running' ? ' · ' + formatRate(job.rate ?? 0, speedUnit) : ''}
            {job.state === 'held' ? ' · waiting for the Turbo transfer' : ''}</small>
          {percent !== null && <span className="queue-progress"><span style={{ width: percent + '%' }}/></span>}
        </button>
        <div className="job-meta"><span className={'priority-chip' + (job.turbo ? ' turbo-chip' : '')}>{job.turbo ? 'Turbo' : job.priority}</span>
          <span className="queue-amount">{percent === null ? mib(complete) : percent.toFixed(0) + '%'}</span></div>
        {canControl && <div className="job-actions">
          <button type="button" className={'quiet turbo-button' + (job.turbo ? ' is-turbo' : '')} aria-pressed={Boolean(job.turbo)}
            disabled={!apiReady || job.routing === 'scanning' || (job.state === 'held' || job.state === 'paused' && !job.turbo)} onClick={() => turbo(job.id, !job.turbo)}
            title="Reserve all available connections for this file and hold other transfers"><Zap size={14} aria-hidden/>{job.turbo ? 'Exit Turbo' : 'Turbo'}</button>
          <button type="button" className="icon-button quiet" disabled={!apiReady || job.routing !== 'range' || job.state === 'held'}
            onClick={() => control(job.id, job.state === 'paused' ? 'resume' : 'pause')}
            aria-label={(job.state === 'paused' ? 'Resume ' : 'Pause ') + job.filename} title={job.state === 'paused' ? 'Resume' : 'Pause'}>
            {job.state === 'paused' ? <Play size={15} aria-hidden/> : <Pause size={15} aria-hidden/>}</button>
          <button type="button" className="icon-button quiet" disabled={!apiReady || job.routing === 'scanning'}
            onClick={() => control(job.id, 'cancel')} aria-label={'Cancel ' + job.filename} title="Cancel"><X size={15} aria-hidden/></button>
        </div>}
        {recoverable && <div className="job-actions">
          <button type="button" className="quiet" disabled={!apiReady || !chosen.length} onClick={() => resume(job.id)}><Play size={14} aria-hidden/>Resume saved</button>
          <button type="button" className="quiet" disabled={!apiReady} onClick={() => updateQueue('cancel_waiting', job.id, null)}>Discard</button>
        </div>}
        {job.state === 'queued' && <div className="job-actions">
          <Dropdown label={'Priority for ' + job.filename} value={job.priority} options={priorities}
            onChange={value => updateQueue('change_priority', job.id, value)}/>
          <button type="button" className="icon-button quiet" onClick={() => updateQueue('cancel_waiting', job.id, null)}
            aria-label={'Remove ' + job.filename} title="Remove"><X size={15} aria-hidden/></button>
        </div>}
      </li>;
    })}</ul> : <div className="queue-empty"><Download size={22} aria-hidden/><div><strong>Your next download starts here</strong>
      <p>Add a file, choose its connections, and follow its progress.</p></div></div>}
  </section>;
}
