'use strict';
const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
const intro = document.getElementById('site-intro');
let introDismissed = false;
function finishIntro() {
  if (introDismissed) return;
  introDismissed = true;
  document.getElementById('intro-status').textContent = 'Ready.';
  intro.classList.add('is-finishing');
  setTimeout(() => {
    intro.close();
    document.documentElement.classList.add('page-ready');
    updateAnimation();
  }, motion.matches ? 0 : 180);
}
if (!motion.matches && typeof intro.showModal === 'function') {
  intro.showModal();
  document.getElementById('skip-intro').addEventListener('click', finishIntro);
  intro.addEventListener('cancel', event => { event.preventDefault(); finishIntro(); });
  document.fonts.ready.then(finishIntro, finishIntro);
  setTimeout(finishIntro, 2200);
} else {
  introDismissed = true;
  document.documentElement.classList.add('page-ready');
}
for (const heading of document.querySelectorAll('.reveal h2')) {
  for (const node of [...heading.childNodes]) {
    if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
      const line = document.createElement('span'); line.className = 'headline-line';
      line.textContent = node.textContent; node.replaceWith(line);
    } else if (node.nodeName === 'BR') node.remove();
  }
}
if (!motion.matches && 'IntersectionObserver' in window) {
  document.documentElement.classList.add('js-motion');
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      entry.target.classList.add('visible'); observer.unobserve(entry.target);
    }
  }, { threshold: 0.06 });
  document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
}
const sources = [...document.querySelectorAll('.path-source')];
const turbo = document.getElementById('demo-turbo');
function updateDiagram() {
  const count = sources.filter(button => button.getAttribute('aria-pressed') === 'true').length;
  document.getElementById('path-count').textContent = count + (count === 1 ? ' path selected' : ' paths selected');
  for (const button of sources) document.querySelector('[data-route="' + button.dataset.path + '"]').dataset.off = String(button.getAttribute('aria-pressed') !== 'true');
  document.getElementById('diagram-message').textContent = count ? 'One file. Your chosen routes.' : 'Choose a connection above.';
}
for (const button of sources) button.addEventListener('click', () => {
  button.setAttribute('aria-pressed', String(button.getAttribute('aria-pressed') !== 'true'));
  turbo.setAttribute('aria-pressed', 'false');
  turbo.querySelector('.turbo-label').textContent = 'Try Turbo';
  document.querySelector('.hero-visual').dataset.turbo = 'false';
  updateDiagram();
});
turbo.addEventListener('click', () => {
  const enabled = turbo.getAttribute('aria-pressed') !== 'true';
  turbo.setAttribute('aria-pressed', String(enabled));
  turbo.querySelector('.turbo-label').textContent = enabled ? 'Exit Turbo' : 'Try Turbo';
  document.querySelector('.hero-visual').dataset.turbo = String(enabled);
  if (enabled) sources.forEach(button => button.setAttribute('aria-pressed', 'true'));
  document.querySelectorAll('animateMotion').forEach(element => element.setAttribute('dur', enabled ? '1.1s' : '3.2s'));
  updateDiagram();
  if (enabled) document.getElementById('diagram-message').textContent = 'Turbo illustration: all routes, one file.';
});
const heroVisual = document.querySelector('.hero-visual');
const diagram = document.querySelector('.flock-diagram');
let diagramVisible = true;
function updateAnimation() {
  const active = diagramVisible && !document.hidden && !motion.matches && document.documentElement.classList.contains('page-ready');
  heroVisual.dataset.paused = String(!active);
  if (active) diagram.unpauseAnimations(); else diagram.pauseAnimations();
}
if ('IntersectionObserver' in window) {
  new IntersectionObserver(entries => { diagramVisible = entries[0].isIntersecting; updateAnimation(); }).observe(heroVisual);
}
document.addEventListener('visibilitychange', updateAnimation);
motion.addEventListener('change', updateAnimation);
updateAnimation();
function openHash() {
  let id;
  try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
  const target = document.getElementById(id);
  if (target?.tagName === 'DETAILS') target.open = true;
}
window.addEventListener('hashchange', openHash);
openHash();
let checksum = '';
fetch('release.json', { cache: 'no-cache' }).then(response => {
  if (!response.ok) throw new Error('Release unavailable');
  return response.json();
}).then(release => {
  if (!release.available || !/^\d+\.\d+\.\d+$/.test(release.version) ||
      !/^[a-f0-9]{64}$/i.test(release.sha256) ||
      !/^https:\/\/github\.com\/Rajeshkumarg-14\/fetchvolt-site\/releases\/download\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+\.zip$/.test(release.url)) throw new Error('Release unavailable');
  checksum = release.sha256.toUpperCase();
  document.getElementById('download-button').href = release.url;
  document.getElementById('release-description').textContent = 'Version ' + release.version + ' · Windows x64 · ' + (release.bytes / 1048576).toFixed(1) + ' MiB ZIP';
  document.getElementById('checksum').textContent = checksum;
  document.getElementById('copy-checksum').disabled = false;
}).catch(() => {
  document.getElementById('release-description').textContent = 'Check GitHub Releases for available setup files.';
  document.getElementById('checksum').textContent = 'Use the SHA256SUMS.txt attached to the release.';
});
document.getElementById('copy-checksum').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(checksum); document.getElementById('copy-status').textContent = 'Checksum copied.'; }
  catch { document.getElementById('copy-status').textContent = 'Select the checksum above and copy it manually.'; }
});
