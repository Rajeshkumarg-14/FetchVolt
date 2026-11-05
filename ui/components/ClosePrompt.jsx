import React, { useEffect, useRef, useState } from 'react';
import { Download, ShieldCheck } from 'lucide-react';

export function ClosePrompt({ api }) {
  const dialog = useRef(null);
  const [open, setOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const request = () => { setError(''); setOpen(true); };
    window.addEventListener('portflock-close-request', request);
    return () => window.removeEventListener('portflock-close-request', request);
  }, []);
  useEffect(() => {
    const element = dialog.current;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  async function close(action) {
    setStopping(true);
    setError('');
    try {
      const problem = await api.close_app(action);
      if (problem) { setError(problem); setStopping(false); }
    } catch {
      setError('FetchVolt could not finish closing. Keep the window open and try again.');
      setStopping(false);
    }
  }
  return <dialog className="close-dialog" ref={dialog} role="alertdialog" aria-labelledby="close-title" aria-describedby="close-description"
    onCancel={event => { event.preventDefault(); if (!stopping) setOpen(false); }}>
    <span className="close-symbol"><Download size={23} aria-hidden/></span>
    <h2 id="close-title">Close FetchVolt?</h2>
    <p id="close-description">There are unfinished downloads. Save their completed ranges to resume when you return, or cancel them before closing.</p>
    <p className="close-detail"><ShieldCheck size={16} aria-hidden/>Single-stream downloads without range support start again when added later.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {stopping ? <p className="close-stopping" role="status">Stopping downloads…</p> : <div className="close-actions">
      <button type="button" className="primary" disabled={!api} onClick={() => close('save')}>Save progress and close</button>
      <button type="button" className="quiet" disabled={!api} onClick={() => close('cancel')}>Cancel downloads and close</button>
      <button type="button" className="quiet" autoFocus onClick={() => setOpen(false)}>Keep open</button>
    </div>}
  </dialog>;
}
