import React, { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { LazyMotion, MotionConfig, domAnimation, useReducedMotion } from 'motion/react';
import { Activity, ArrowRight, Bot, Clock3, Download, HardDrive, Plus, RefreshCw, Settings2, ShieldCheck, Zap } from 'lucide-react';
import { TransferTree, mib } from './components/TransferTree';
import { Dropdown } from './components/Dropdown';
import { ClosePrompt } from './components/ClosePrompt';
import { DownloadComposer } from './components/DownloadComposer';
import { TransferQueue } from './components/TransferQueue';
import { Settings } from './components/Settings';
import { NetworkSpeedTest } from './components/NetworkSpeedTest';
import { Storage } from './components/Storage';
import { McpControl, McpSummary } from './components/McpControl';
import { ConnectionSpeeds, SpeedSummary } from './components/SpeedGauges';
import { formatRate, formatStorage } from './metrics.mjs';
import logo from '../branding/fetchvolt.svg';
import './styles.css';

const empty = { rows: [], storage: [], storageUpdated: '', jobs: [], maxConnections: 7, updated: '',
  systemTheme: 'dark', reducedMotion: false, startup: { supported: false, enabled: false }, turboId: null };
const defaultPreferences = { theme: 'system', layout: 'auto', motion: 'system', speed: 'mbps', surface: 'solid', displayName: 'My workspace' };
const narrowWindow = window.matchMedia('(max-width: 900px)');
function subscribeToWidth(callback) {
  narrowWindow.addEventListener('change', callback);
  return () => narrowWindow.removeEventListener('change', callback);
}
const isNarrow = () => narrowWindow.matches;
const views = [
  { value: 'download', label: 'Downloads', icon: Download, description: 'Your connections, working together.' },
  { value: 'network', label: 'Network', icon: Activity, description: 'Live adapter activity across your PC.' },
  { value: 'history', label: 'History', icon: Clock3, description: 'Connection changes and completed transfers.' },
  { value: 'mcp', label: 'AI & MCP', icon: Bot, description: 'Put your downloads within reach of your AI tools.' },
  { value: 'settings', label: 'Settings', icon: Settings2, description: 'Make this workspace your own.' },
];

function useDesktop() {
  const [api, setApi] = useState(() => window.pywebview?.api);
  const [state, setState] = useState(empty);
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [loaded, setLoaded] = useState(false);
  const [problem, setProblem] = useState('');
  const lastResponse = useRef(0);
  const [stale, setStale] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => setStale(lastResponse.current > 0 && Date.now() - lastResponse.current > 5000), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const ready = () => setApi(window.pywebview.api);
    window.addEventListener('pywebviewready', ready);
    if (window.pywebview?.api) ready();
    return () => window.removeEventListener('pywebviewready', ready);
  }, []);
  useEffect(() => {
    if (loaded) return;
    const timeout = setTimeout(() => setProblem('The desktop service is taking longer than expected to start.'), 12000);
    return () => clearTimeout(timeout);
  }, [loaded]);
  useEffect(() => {
    if (!api) return;
    let cancelled = false;
    let timer;
    async function poll() {
      try {
        const next = await api.state();
        if (!cancelled) { lastResponse.current = Date.now(); setState({ ...empty, ...next }); setLoaded(true); setProblem(''); }
      } catch {
        if (!cancelled) setProblem('The desktop connection was interrupted. Reconnecting…');
      } finally {
        if (!cancelled) timer = setTimeout(poll, 500);
      }
    }
    api.preferences().then(value => {
      if (!cancelled) setPreferences({ ...defaultPreferences, ...value });
    }).catch(() => {});
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [api]);
  return { api, state, setState, preferences, setPreferences, loaded, problem, stale };
}

function Sidebar({ screen, navigate, state, displayName }) {
  const drive = state.storage.find(item => item.drive === 'P:') || state.storage[0];
  const initials = displayName.trim().split(/\s+/).slice(0, 2).map(word => Array.from(word)[0] || '').join('').toLocaleUpperCase();
  const active = state.jobs.filter(job => ['running', 'paused', 'reconnecting', 'held'].includes(job.state)).length;
  return <aside className="sidebar">
    <div className="brand"><img src={logo} width="37" height="37" alt=""/><div><strong>FetchVolt</strong><small>Download workspace</small></div></div>
    <nav className="side-navigation" aria-label="Workspace">{views.map(({ value, label, icon: Icon }) =>
      <button type="button" className="nav-item" key={value} aria-current={screen === value ? 'page' : undefined}
        aria-label={label} title={label} onClick={() => navigate(value)}><Icon size={18} aria-hidden/><span>{label}</span>
        {value === 'download' && active > 0 && <b>{active}</b>}</button>
    )}</nav>
    <div className="sidebar-bottom">{drive && <div className="sidebar-storage"><div><HardDrive size={13} aria-hidden/><span>Drive {drive.drive}</span></div>
      <meter aria-label={'Space used on drive ' + drive.drive} min={0} max={drive.total} value={drive.total - drive.free}/>
      <small>{formatStorage(drive.free)} free of {formatStorage(drive.total)}</small></div>}
      <div className="profile"><span className="profile-avatar" aria-hidden>{initials}</span><div><strong title={displayName}>{displayName}</strong><small>Local workspace</small></div></div>
    </div>
  </aside>;
}

function Network({ api, state, speedUnit, rows, turbo, reduce }) {
  return <div className="network-page">
    <div className="network-summary"><SpeedSummary rows={rows} unit={speedUnit} turbo={turbo} reduce={reduce} updated={state.updated} networkError={state.networkError}/>
      <section className="surface network-explanation"><Activity size={23} aria-hidden/><h2>Every active connection</h2>
        <p>Rates include traffic from all apps on adapters with an IPv4 gateway. The aggregate excludes disconnected and virtual-only routes.</p>
        <dl><div><dt>Last reading</dt><dd>{state.updated || 'Reading…'}</dd></div><div><dt>Eligible connections</dt><dd>{rows.length}</dd></div></dl>
        {state.networkError && <p className="error">{state.networkError}</p>}</section></div>
    {rows.length > 0 && <ConnectionSpeeds rows={rows} unit={speedUnit} turbo={turbo} reduce={reduce}/>}
    <NetworkSpeedTest api={api} test={state.speedTest} rows={rows} unit={speedUnit}/>
    <section className="surface network-table"><header className="section-head"><div><h2>Adapter details</h2><p>Link rate is the local connection negotiated by the adapter.</p></div></header>
      <div className="table-scroll" role="region" aria-label="Network adapter table" tabIndex={0}><table><thead><tr>
        {['Connection', 'Status', 'IPv4', 'Link rate', 'Receive rate', 'Send rate', 'Received', 'Sent'].map(value => <th key={value}>{value}</th>)}
      </tr></thead><tbody>{state.rows.map(row => <tr key={row.index}>
        <th scope="row">{row.name}</th><td><span className={'adapter-status' + (row.status === 'Up' ? ' online' : '')}>{row.status}</span></td><td>{row.ip || '—'}</td><td>{row.link}</td>
        <td>{formatRate(row.rxRate == null ? null : row.rxRate * 125000, speedUnit)}</td><td>{formatRate(row.txRate == null ? null : row.txRate * 125000, speedUnit)}</td>
        <td>{row.rx == null ? '—' : mib(row.rx)}</td><td>{row.tx == null ? '—' : mib(row.tx)}</td>
      </tr>)}</tbody></table></div>
    </section>
  </div>;
}

function History({ records, error }) {
  return <section className="surface"><header className="section-head"><div><h2>Recent activity</h2><p>Connection changes and finished downloads stored on this PC.</p></div></header>
    {error ? <p className="error" role="alert">{error}</p> : records === null ? <p>Loading history…</p> : records.length === 0 ? <p className="empty">Your connection and download events will appear here.</p> :
      <div className="table-scroll" role="region" aria-label="History table" tabIndex={0}><table><thead><tr>
        {['Local time', 'Type', 'Adapter or file', 'Result', 'Details'].map(value => <th key={value}>{value}</th>)}
      </tr></thead><tbody>{records.map(([time, category, subject, outcome, details], index) =>
        <tr key={time + '-' + subject + '-' + index}><td>{time.slice(0, 19).replace('T', ' ')}</td><td>{category}</td><th scope="row">{subject}</th><td>{outcome}</td><td>{details}</td></tr>
      )}</tbody></table></div>}
  </section>;
}

function Loading({ apiReady, problem }) {
  return <div className="loading-screen" aria-busy={!problem}><div className="loading-focus"><div className="loading-brand"><img src={logo} width="76" height="76" alt=""/></div></div>
    <h1>FetchVolt</h1><p role="status">{problem || (apiReady ? 'Reading your connections…' : 'Connecting to the desktop…')}</p>
    <ul className="loading-stages" aria-label="Startup status"><li data-ready={apiReady}><span aria-hidden/>{apiReady ? 'Desktop connected' : 'Waiting for desktop'}</li>
      <li data-pending={apiReady && !problem}><span aria-hidden/>{problem ? 'Waiting to retry' : 'Loading live readings'}</li></ul>
    {problem && <button type="button" className="quiet" onClick={() => window.location.reload()}>Try again</button>}
  </div>;
}

function App() {
  const { api, state, setState, preferences, setPreferences, loaded, problem, stale } = useDesktop();
  const prefersReducedMotion = useReducedMotion();
  const narrow = useSyncExternalStore(subscribeToWidth, isNarrow);
  const [screen, setScreen] = useState('download');
  const [selection, setSelection] = useState(null);
  const [url, setUrl] = useState('');
  const [priority, setPriority] = useState('normal');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [settingsError, setSettingsError] = useState('');
  const [startupBusy, setStartupBusy] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [routingMessage, setRoutingMessage] = useState('');
  const [selectedJob, setSelectedJob] = useState(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [records, setRecords] = useState(null);
  const [historyError, setHistoryError] = useState('');
  const [browserBusy, setBrowserBusy] = useState(false);
  const [browserMessage, setBrowserMessage] = useState('');
  const pageHeading = useRef(null);
  useEffect(() => {
    if (!api || screen !== 'history') return;
    let current = true;
    api.history().then(value => { if (current) { setRecords(value); setHistoryError(''); } })
      .catch(() => { if (current) setHistoryError('Local history is unavailable.'); });
    return () => { current = false; };
  }, [api, screen, state.historyRevision]);
  const mode = preferences.theme === 'system' ? state.systemTheme : preferences.theme;
  const reduce = preferences.motion === 'off' || state.reducedMotion || prefersReducedMotion;
  useEffect(() => { document.documentElement.dataset.theme = mode; }, [mode]);
  useEffect(() => { document.documentElement.dataset.surface = preferences.surface; }, [preferences.surface]);
  useEffect(() => { document.documentElement.dataset.reducedMotion = String(Boolean(reduce)); }, [reduce]);
  const eligible = state.rows.filter(row => row.status === 'Up' && row.gateway)
    .sort((a, b) => Number(b.name === 'Wi-Fi') - Number(a.name === 'Wi-Fi') || a.name.localeCompare(b.name));
  const ids = new Set(selection ?? eligible.slice(0, 1).map(row => row.index));
  const chosen = eligible.filter(row => ids.has(row.index));
  const fallback = state.jobs.find(job => ['running', 'paused', 'reconnecting', 'held'].includes(job.state)) || state.jobs[0];
  const focused = selectedJob === 'connections' ? null : state.jobs.find(job => job.id === selectedJob) || fallback;
  const transferAdapters = focused?.state === 'recoverable' ? chosen.map(row => row.name) : focused?.selectedAdapters ?? Object.keys(focused?.totals ?? {});
  const entries = focused ? transferAdapters.map(name => [name, focused.totals[name] ?? 0]) : chosen.map(row => [row.name, 0]);
  const routingChanged = focused?.selectedAdapters?.length !== chosen.length || chosen.some(row => !focused?.selectedAdapters?.includes(row.name));
  const orientation = preferences.layout === 'auto' ? (narrow ? 'vertical' : 'horizontal') : preferences.layout;
  const page = views.find(view => view.value === screen);
  const turboActive = state.turboId != null;
  const readingsDelayed = stale || Boolean(problem) || Boolean(state.networkError) || (state.trafficAge != null && state.trafficAge > 3);

  function navigate(next) {
    setScreen(next);
    requestAnimationFrame(() => pageHeading.current?.focus({ preventScroll: true }));
  }
  function toggle(index) {
    setSelection(chosen.some(row => row.index === index) ? chosen.filter(row => row.index !== index).map(row => row.index) : [...chosen.map(row => row.index), index]);
  }
  async function enqueue(event) {
    event.preventDefault(); setError(''); setSubmitting(true);
    try {
      const result = await api.start(url.trim(), chosen.map(row => row.index), priority);
      if (typeof result === 'string') setError(result);
      if (typeof result === 'number') { setSelectedJob(result); setUrl(''); setComposerOpen(false); }
    } catch { setError('Could not queue the download.'); }
    finally { setSubmitting(false); }
  }
  async function updateQueue(action, identifier, nextPriority) {
    try {
      const changed = nextPriority === null ? await api[action](identifier) : await api[action](identifier, nextPriority);
      if (!changed) setError('That download has already started.');
    } catch { setError('Could not update the queue.'); }
  }
  async function controlDownload(identifier, action) {
    setError('');
    try { const message = await api.control_download(identifier, action); if (message) setError(message); }
    catch { setError('Could not update this transfer.'); }
  }
  async function resumeDownload(identifier) {
    setError('');
    try {
      const message = await api.resume_download(identifier, chosen.map(row => row.index));
      if (message) setError(message); else setSelectedJob(identifier);
    } catch { setError('Could not resume the saved download.'); }
  }
  async function setTurbo(identifier, enabled) {
    setError('');
    try { const message = await api.set_turbo(identifier, enabled); if (message) setError(message); }
    catch { setError('Could not change Turbo for this transfer.'); }
  }
  async function applyConnections() {
    if (!focused || !api) return;
    try {
      const message = await api.apply_connections(focused.id, chosen.map(row => row.index));
      setRoutingMessage(message || 'Updated. In-flight chunks will finish on their original links.');
    } catch { setRoutingMessage('Could not update this download’s connections.'); }
  }
  async function changePreference(name, value) {
    setPreferences(previous => ({ ...previous, [name]: value })); setSettingsError('');
    try { if (name === 'theme') await api?.set_theme(value); else await api?.set_transfer_preference(name, value); }
    catch { setSettingsError('This preference could not be saved. Try changing it again.'); }
  }
  async function changeStartup(enabled) {
    setStartupBusy(true); setSettingsError('');
    try { const startup = await api.set_startup(enabled); setState(previous => ({ ...previous, startup })); }
    catch { setSettingsError('Windows startup could not be changed. Check the diagnostic log.'); }
    finally { setStartupBusy(false); }
  }
  async function saveDisplayName(value) {
    setProfileBusy(true); setProfileError('');
    try {
      const normalized = await api.set_display_name(value);
      if (typeof normalized !== 'string' || !normalized.trim()) throw new Error('Invalid display name response');
      setPreferences(previous => ({ ...previous, displayName: normalized }));
      return normalized;
    } catch { setProfileError('Could not save the name. Use 1–40 visible characters and try again.'); return null; }
    finally { setProfileBusy(false); }
  }
  const showComposer = composerOpen || state.jobs.length === 0;
  async function browserSetup() {
    setBrowserBusy(true); setBrowserMessage('');
    try { await api.setup_browser_extension(); setBrowserMessage('Setup guide opened. Enable the extension in your browser.'); }
    catch { setBrowserMessage('Setup failed. Check the diagnostic log and try again.'); }
    finally { setBrowserBusy(false); }
  }
  return <MotionConfig reducedMotion={reduce ? 'always' : 'user'}><LazyMotion features={domAnimation}>
    <ClosePrompt api={api}/>
    {!loaded ? <Loading apiReady={Boolean(api)} problem={problem}/> : <div className="app-frame">
      <Sidebar screen={screen} navigate={navigate} state={state} displayName={preferences.displayName}/>
      <main className="main-workspace">
        <header className="toolbar"><div><h1 ref={pageHeading} tabIndex={-1}>{page.label}</h1><p>{page.description}</p></div>
          <div className="toolbar-actions"><span className={'reading-status' + (readingsDelayed ? ' stale' : '')} title={'Last adapter discovery: ' + (state.updated || 'Waiting')}>{readingsDelayed ? 'Readings delayed' : 'Live readings'}<span className="reading-time">{state.updated || 'Waiting'}</span></span><Dropdown id="toolbar-theme" label="Theme" value={preferences.theme} options={[{value: 'system',label: 'System'}, {value: 'dark',label: 'Dark'}, {value: 'light',label: 'Light'}]} onChange={value => changePreference('theme', value)}/>{turboActive && <span className="turbo-indicator"><Zap size={13} aria-hidden/>Turbo active</span>}
            {screen === 'download' && <button type="button" className="primary" onClick={() => setComposerOpen(value => !value)}><Plus size={16} aria-hidden/>New download</button>}
            {screen === 'network' && <button type="button" className="quiet" onClick={() => api.refresh()}><RefreshCw size={15} aria-hidden/>Refresh</button>}</div>
        </header>
        <div className="workspace-content" tabIndex={0} aria-label={page.label + ' content'}>
        {problem && <p className="connection-alert" role="status">{problem}</p>}
        {screen === 'download' && <div className="download-page">
          <div className="overview"><SpeedSummary rows={eligible} unit={preferences.speed} turbo={turboActive} reduce={reduce} updated={state.updated} networkError={state.networkError}/>
            <div className="transfer-focus"><TransferTree key={focused?.id ?? 'preview'} entries={entries} job={focused} rows={state.rows} reduce={reduce} orientation={orientation} speedUnit={preferences.speed}/>
              {focused && <div className="focus-actions"><button type="button" className="quiet small-button" onClick={() => { setSelectedJob('connections'); setRoutingMessage(''); }}>Show selected connections</button>
                <button type="button" className="quiet small-button" onClick={() => setComposerOpen(true)}>Edit connections <ArrowRight size={13} aria-hidden/></button></div>}</div>
          </div>
          {showComposer && <DownloadComposer eligible={eligible} chosen={chosen} maximum={state.maxConnections} toggle={toggle} url={url} setUrl={setUrl}
            priority={priority} setPriority={setPriority} submit={enqueue} busy={submitting || state.choosing} apiReady={Boolean(api)} refresh={() => api.refresh()}
            error={error} focused={focused} routingChanged={routingChanged} applyConnections={applyConnections} routingMessage={routingMessage}
            close={state.jobs.length ? () => setComposerOpen(false) : null}/>}
          {eligible.length > 0 && <><div className="section-heading"><h2>Connections</h2><p>All app traffic · {eligible.length} available</p></div>
            <ConnectionSpeeds rows={eligible} unit={preferences.speed} turbo={turboActive} reduce={reduce}/></>}
          <div className="download-lower"><TransferQueue jobs={state.jobs} selected={focused?.id} select={identifier => { setSelectedJob(identifier); setRoutingMessage(''); }}
            apiReady={Boolean(api)} chosen={chosen} speedUnit={preferences.speed} control={controlDownload} resume={resumeDownload} updateQueue={updateQueue} turbo={setTurbo}/>
            <McpSummary open={() => navigate('mcp')}/></div>
          {!showComposer && error && <p className="error workspace-error" role="alert">{error}</p>}
        </div>}
        {screen === 'network' && <Network api={api} state={state} rows={eligible} speedUnit={preferences.speed} turbo={turboActive} reduce={reduce}/>}
        {screen === 'history' && <History records={records} error={historyError}/>}
        {screen === 'mcp' && <McpControl api={api}/>}
        {screen === 'settings' && <div className="settings-workspace"><Settings preferences={preferences} change={changePreference} error={settingsError}
          startup={state.startup} changeStartup={changeStartup} startupBusy={startupBusy} browserSetup={browserSetup} browserBusy={browserBusy} browserMessage={browserMessage}
          saveDisplayName={saveDisplayName} profileBusy={profileBusy} profileError={profileError}/><Storage drives={state.storage} updated={state.storageUpdated}/></div>}
        </div>
        <footer className="workspace-footer"><span><ShieldCheck size={13} aria-hidden/>Defender scan before publishing</span><span>Copyright © 2026 Rajesh Kumar G</span></footer>
      </main>
    </div>}
  </LazyMotion></MotionConfig>;
}

createRoot(document.getElementById('root')).render(<App/>);
