import React, { useEffect, useState } from 'react';
import { ArrowRight, Bot, Check, Copy, FolderDown, Terminal } from 'lucide-react';
import { copyText } from '../clipboard.mjs';

function configuration(setup, folder) {
  return setup?.command ? JSON.stringify({ mcpServers: { portflock: {
    command: setup.command, args: [...(setup.args || ['run', '--script', '--python', '3.14', setup.scriptPath]), '--root', folder],
  } } }, null, 2) : '';
}

export function McpSummary({ open }) {
  return <section className="surface mcp-summary"><header className="section-head"><h2>AI & MCP</h2><span className="muted small">Local stdio</span></header>
    <div className="mcp-summary-body"><p className="mcp-purpose"><Bot size={17} aria-hidden/> Download through your AI client</p>
      <p>Choose an output folder and connect your MCP host.</p>
      <button type="button" className="quiet mcp-open" onClick={open}>Set up MCP <ArrowRight size={15} aria-hidden/></button></div>
  </section>;
}

export function McpControl({ api }) {
  const [setup, setSetup] = useState(null);
  const [folder, setFolder] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [preparing, setPreparing] = useState(false);
  const [copying, setCopying] = useState(false);
  useEffect(() => {
    if (!api) return;
    let current = true;
    api.mcp_configuration().then(value => { if (current) { setSetup(value); setFolder(value.defaultRoot || ''); } })
      .catch(() => { if (current) setError('MCP setup details could not be read.'); });
    return () => { current = false; };
  }, [api]);
  const config = configuration(setup, folder);
  const validFolder = /^[a-z]:[\\/]/i.test(folder);
  async function prepare() {
    setPreparing(true);
    setError('');
    try {
      await api.prepare_mcp();
      const next = await api.mcp_configuration();
      setSetup(next);
      if (!folder) setFolder(next.defaultRoot || '');
    } catch {
      setError('MCP files could not be prepared. Check the FetchVolt diagnostic log.');
    } finally {
      setPreparing(false);
    }
  }
  async function copy() {
    setNotice(''); setError(''); setCopying(true);
    try {
      let current = setup;
      if (current.available === false) {
        await api.prepare_mcp();
        current = await api.mcp_configuration();
        setSetup(current);
        if (current.available === false) throw new Error('MCP unavailable');
      }
      await copyText(configuration(current, folder));
      setNotice('Configuration copied. Paste it into your MCP host.');
    } catch {
      setError('Could not prepare or copy the configuration. Select the JSON below and press Ctrl+C, or retry setup.');
    } finally { setCopying(false); }
  }
  return <div className="mcp-workspace">
    <section className="surface mcp-setup"><header className="section-head"><div><h2>Connect your AI workspace</h2>
      <p>Your AI can download files into a folder you choose.</p></div><span className="pill neutral-pill">stdio</span></header>
      <p className="setup-description">An MCP host starts the local FetchVolt server when it needs it. The server shares the download engine and Windows security checks.</p>
      <label className="field" htmlFor="mcp-root">Output folder<input id="mcp-root" value={folder} onChange={event => { setFolder(event.target.value); setNotice(''); }}
        placeholder="P:\\Downloads" spellCheck={false} autoComplete="off"/></label>
      <p className="field-help">Use an existing local folder. The AI can save inside it and its existing subfolders.</p>
      {setup?.available === false && <div className="prepare-mcp"><p>Prepare the local server files before connecting an MCP host.</p>
        <button type="button" className="quiet" disabled={!api || preparing} onClick={prepare}>{preparing ? 'Preparing…' : 'Prepare MCP'}</button></div>}
      {error && <p className="error" role="alert">{error}</p>}
      {!setup && !error && <p className="empty">Reading MCP configuration…</p>}
      <div className="config-heading"><strong>Host configuration</strong><button type="button" className="quiet" disabled={!config || !validFolder || preparing || copying} onClick={copy}><Copy size={14} aria-hidden/>{copying ? 'Copying…' : setup?.available === false ? 'Prepare and copy' : 'Copy configuration'}</button></div>
      <pre className="mcp-config" tabIndex={0} aria-label="MCP host configuration">{config || 'Waiting for the local server path…'}</pre>
      {notice && <p className="notice" role="status"><Check size={14} aria-hidden/>{notice}</p>}
      <p className="field-help">Keep the MCP session open until its downloads finish. Desktop transfers and MCP transfers run in separate sessions.</p>
    </section>
    <section className="surface mcp-tools"><header className="section-head"><div><h2>Available tools</h2><p>Three tools for a complete download.</p></div></header>
      <ul><li><Terminal size={18} aria-hidden/><div><strong>list_connections</strong><p>Find active adapters and their IDs.</p></div></li>
        <li><FolderDown size={18} aria-hidden/><div><strong>start_download</strong><p>Choose a URL, folder, adapters, and optional SHA-256.</p></div></li>
        <li><Bot size={18} aria-hidden/><div><strong>download_status</strong><p>Read progress and get the verified file path.</p></div></li></ul>
      <p className="tool-note">Public HTTPS only. Existing files are preserved. A saved path is returned after verification.</p>
    </section>
  </div>;
}
