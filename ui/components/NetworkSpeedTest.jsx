import React, { useState } from 'react';
import { Activity, Square } from 'lucide-react';
import { Dropdown } from './Dropdown';
import { formatRate } from '../metrics.mjs';

export function NetworkSpeedTest({ api, test, rows, unit }) {
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const connected = rows.filter(row => row.status === 'Up' && row.gateway);
  const adapter = connected.find(row => String(row.index) === selected) || connected[0];
  const running = test?.state === 'running';
  async function start() {
    if (!adapter || busy) return;
    setBusy(true); setError('');
    try { setError(await api.start_speed_test(adapter.index) || ''); }
    catch { setError('Could not start the test. Try again.'); }
    finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true);
    try { await api.cancel_speed_test(); }
    catch { setError('Could not cancel the test. Try again.'); }
    finally { setBusy(false); }
  }
  return <section className="surface speed-test" aria-labelledby="speed-test-title">
    <header className="section-head"><div><h2 id="speed-test-title">Test your connection</h2><p>A small, real download sample over one adapter.</p></div><Activity size={20} aria-hidden/></header>
    <div className="speed-test-controls"><Dropdown id="test-adapter" label="Connection to test" value={adapter ? String(adapter.index) : ''}
      options={connected.map(row => ({value: String(row.index), label: row.kind ? `${row.kind} · ${row.name}` : row.name}))}
      onChange={setSelected} disabled={running || busy || !connected.length}/>
      {running ? <button type="button" className="quiet" disabled={busy} onClick={cancel}><Square size={14} aria-hidden/>Cancel test</button> :
        <button type="button" className="primary" disabled={busy || !adapter} onClick={start}>{busy ? 'Starting…' : 'Start speed test'}</button>}</div>
    <p className="speed-test-disclosure">Uses up to 10 MB (9.54 MiB) of download payload, plus network overhead. Cloudflare receives your public IP. No file is saved. Pause downloads for a clearer result.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {test && test.state !== 'idle' && <div className="speed-test-result" aria-busy={running}>
      <div className="speed-test-status" role="status">{test.phase}{test.name ? ` · ${test.name}` : ''}</div>
      <dl><div><dt>Receive throughput</dt><dd>{formatRate(test.rate, unit)}</dd></div><div><dt>HTTPS response time</dt><dd>{test.latency == null ? '—' : `${test.latency.toFixed(0)} ms`}</dd></div>
        <div><dt>Response variation</dt><dd>{test.jitter == null ? '—' : `${test.jitter.toFixed(0)} ms`}</dd></div><div><dt>Data received</dt><dd>{((test.bytes || 0) / 1048576).toFixed(1)} MiB</dd></div></dl>
      <progress max={test.limit || 10000000} value={test.bytes || 0} aria-label="Speed test sample received"/>
      {test.shortSample && <p>Short sample: repeat to compare. This bounded test may underestimate fast connections.</p>}
      <p>Measures this adapter’s path to Cloudflare. Response time includes HTTPS setup; this is not an ICMP ping, upload test, or a combined-link speed estimate.</p>
    </div>}
    {test?.history?.length > 0 && <details className="speed-test-history"><summary>Recent tests · this session</summary><ol>{test.history.map((row, index) =>
      <li key={`${row.finished}-${index}`}><span>{row.name}</span><strong>{formatRate(row.rate, unit)}</strong><time dateTime={row.finished}>{new Date(row.finished).toLocaleTimeString()}</time></li>)}</ol></details>}
  </section>;
}
