import React, { useEffect, useState } from 'react';
import { ArrowDown, ArrowRight, Monitor } from 'lucide-react';
import { Dropdown } from './Dropdown';
import { speedOptions } from '../metrics.mjs';

const themes = ['System', 'Light', 'Dark'].map(label => ({ label, value: label.toLowerCase() }));
const motion = [{ label: 'Follow Windows', value: 'system' }, { label: 'Off', value: 'off' }];
const layouts = [
  { value: 'auto', title: 'Auto', detail: 'Adapts to window width', icon: Monitor },
  { value: 'vertical', title: 'Vertical', detail: 'Flows top to bottom', icon: ArrowDown },
  { value: 'horizontal', title: 'Horizontal', detail: 'Flows left to right', icon: ArrowRight },
];

export function Settings({ preferences, change, error, startup, changeStartup, startupBusy, browserSetup, browserBusy, browserMessage, saveDisplayName, profileBusy, profileError }) {
  const [displayName, setDisplayName] = useState(preferences.displayName || 'My workspace');
  const [profileSaved, setProfileSaved] = useState(false);
  useEffect(() => { setDisplayName(preferences.displayName || 'My workspace'); }, [preferences.displayName]);
  async function saveProfile(event) {
    event.preventDefault();
    setProfileSaved(false);
    const normalized = await saveDisplayName(displayName);
    if (typeof normalized === 'string') { setDisplayName(normalized); setProfileSaved(true); }
  }
  return <section className="surface settings">
    <header className="section-head"><div><h2>Workspace preferences</h2>
      <p>Personalize your download workspace.</p></div></header>
    <form className="profile-settings" onSubmit={saveProfile}>
      <div><label htmlFor="display-name">Display name</label><p>The name shown in your local workspace.</p></div>
      <div className="profile-input-row"><input id="display-name" type="text" value={displayName} maxLength={40} required
        autoComplete="nickname" disabled={profileBusy} onChange={event => { setDisplayName(event.target.value); setProfileSaved(false); }}/>
        <button type="submit" className="quiet" disabled={profileBusy || !displayName.trim() || displayName === preferences.displayName}>{profileBusy ? 'Saving…' : 'Save'}</button></div>
      {profileError && <p className="error" role="alert">{profileError}</p>}
      {profileSaved && !profileError && <p className="profile-saved" role="status">Display name saved.</p>}
    </form>
    <div className="setting-row">
      <div><label htmlFor="appearance">Appearance</label><p>Choose a theme or follow Windows.</p></div>
      <Dropdown id="appearance" label="Appearance" value={preferences.theme} options={themes}
        onChange={value => change('theme', value)}/>
    </div>
    <div className="setting-row">
      <div><label htmlFor="surface-style">Surface style</label><p>Clean solid panels or translucent glass.</p></div>
      <Dropdown id="surface-style" label="Surface style" value={preferences.surface || 'solid'} options={[{value: 'solid', label: 'Solid'}, {value: 'glass', label: 'Glass'}]} onChange={value => change('surface', value)}/>
    </div>
    <div className="setting-row">
      <div><label htmlFor="speed-unit">Speed units</label><p>Used for network rates and active downloads.</p></div>
      <Dropdown id="speed-unit" label="Speed units" value={preferences.speed} options={speedOptions}
        onChange={value => change('speed', value)}/>
    </div>
    <fieldset className="layout-settings">
      <legend>Transfer tree layout</legend>
      <p>For multiple connections. A single connection always uses the compact route.</p>
      <div className="layout-options">{layouts.map(({ value, title, detail, icon: Icon }) =>
        <label key={value} className="layout-option">
          <input type="radio" name="tree-layout" value={value} checked={preferences.layout === value}
            onChange={() => change('layout', value)}/>
          <Icon size={18} aria-hidden/>
          <span><strong>{title}</strong><small>{detail}</small></span>
        </label>)}
      </div>
    </fieldset>
    <div className="setting-row">
      <div><label htmlFor="animation">Animations</label><p>Control transfer pulses and interface motion.</p></div>
      <Dropdown id="animation" label="Animations" value={preferences.motion} options={motion}
        onChange={value => change('motion', value)}/>
    </div>
    <div className="setting-row startup-setting">
      <div><label htmlFor="launch-startup">Launch at Windows sign-in</label><p>Keep FetchVolt ready when you sign in.</p>
        {startup?.supported === false && <small>Available in the installed Windows app.</small>}</div>
      <input id="launch-startup" className="switch-input" type="checkbox" checked={Boolean(startup?.enabled)}
        disabled={!startup?.supported || startupBusy} onChange={event => changeStartup(event.target.checked)}/>
    </div>
    <div className="setting-row">
      <div><strong>Browser extension</strong><p>Optional download handoff for Edge, Chrome and compatible browsers.</p>
        {browserMessage && <p role="status">{browserMessage}</p>}</div>
      <button type="button" className="quiet" disabled={browserBusy || !startup?.supported} onClick={browserSetup}>{browserBusy ? 'Preparing…' : 'Set up extension'}</button>
    </div>
    <footer className="about" aria-label="About FetchVolt">
      <strong>About FetchVolt</strong>
      <div className="about-metadata"><div><span>Created by</span><p>Rajesh Kumar G</p><small>Copyright © 2026 Rajesh Kumar G</small></div>
        <div><span>Find the creator</span><p>GitHub: Rajeshkumarg-14</p><p>rajeshkumarg.com</p></div>
        <div className="about-logs"><span>Diagnostic logs</span><code>%LOCALAPPDATA%\Net Booster\logs</code></div></div>
    </footer>
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
