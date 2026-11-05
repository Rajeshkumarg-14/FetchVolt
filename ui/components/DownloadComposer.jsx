import React from 'react';
import { ArrowDownToLine, RefreshCw, X } from 'lucide-react';
import { Dropdown } from './Dropdown';
import { AdapterIcon } from './TransferTree';

const priorities = ['high', 'normal', 'low'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) }));

export function DownloadComposer({ eligible, chosen, maximum, toggle, url, setUrl, priority, setPriority, submit,
  busy, apiReady, refresh, error, focused, routingChanged, applyConnections, routingMessage, close }) {
  return <section className="surface composer" aria-labelledby="new-download-title">
    <header className="section-head"><div><h2 id="new-download-title">New download</h2><p>Choose the connections that will carry your file.</p></div>
      {close && <button type="button" className="icon-button quiet" aria-label="Close new download form" onClick={close}><X size={17} aria-hidden/></button>}</header>
    <form onSubmit={submit}>
      <label className="field" htmlFor="download-url">HTTPS file URL<input id="download-url" type="url" required value={url}
        onChange={event => setUrl(event.target.value)} placeholder="https://example.com/file.zip" autoComplete="off"/></label>
      <fieldset className="connection-picker"><legend>Connections <small>{chosen.length} / {maximum} selected</small></legend>
        <div className="adapter-options">{eligible.length ? eligible.map(row => {
          const checked = chosen.some(item => item.index === row.index);
          return <label className="adapter" key={row.index}><AdapterIcon name={row.kind || row.name}/>
            <span>{row.name}<small>{row.kind ? row.kind + ' · ' : ''}{row.link}</small></span>
            <input type="checkbox" checked={checked} disabled={!checked && chosen.length >= maximum} onChange={() => toggle(row.index)}/>
          </label>;
        }) : <p className="empty">Connect an adapter with IPv4 internet access, then refresh.</p>}</div>
      </fieldset>
      <div className="form-actions"><div className="field priority"><label htmlFor="download-priority">Priority</label>
        <Dropdown id="download-priority" label="Download priority" value={priority} options={priorities} onChange={setPriority}/></div>
        <button type="button" className="quiet" disabled={!apiReady} onClick={refresh}><RefreshCw size={15} aria-hidden/>Refresh</button>
        <button type="submit" className="primary" disabled={!apiReady || busy || !chosen.length}><ArrowDownToLine size={16} aria-hidden/>{busy ? 'Choosing…' : 'Add download'}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
    {['running', 'paused', 'reconnecting', 'held'].includes(focused?.state) && <div className="routing-controls">
      <div><strong>Connections for {focused.filename}</strong><p>{focused.turbo ? 'Turbo manages all available connections for this file.'
        : focused.routing === 'range' ? 'Apply the selection above to upcoming chunks.'
        : focused.routing === 'single' ? 'This server supports one connection for this download.'
        : focused.routing === 'scanning' ? 'The file is being verified.' : 'Checking the server’s range support.'}</p></div>
      <button type="button" className="quiet" disabled={!apiReady || focused.turbo || focused.routing !== 'range' || !chosen.length || !routingChanged}
        onClick={applyConnections}>Apply to active download</button>
      {routingMessage && <p role="status">{routingMessage}</p>}
    </div>}
  </section>;
}
