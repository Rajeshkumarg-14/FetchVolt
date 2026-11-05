import { build } from 'esbuild';
import { createHash } from 'node:crypto';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';

const result = await build({
  entryPoints: ['src.jsx'], bundle: true, minify: true, write: false, metafile: true,
  outdir: 'dist', target: 'chrome120', legalComments: 'inline',
  loader: { '.svg': 'dataurl', '.ttf': 'dataurl' },
  define: { 'process.env.NODE_ENV': '"production"' },
});
const stylesheet = result.outputFiles.find(file => file.path.endsWith('.css'));
const bundle = result.outputFiles.find(file => file.path.endsWith('.js'));
if (!stylesheet || !bundle) throw new Error('Expected a JavaScript and CSS bundle.');
const css = stylesheet.text;
const js = bundle.text.replaceAll('</script', '<\\/script');
const hash = createHash('sha256').update(js).digest('base64');
const packages = new Set();
for (const output of Object.values(result.metafile.outputs)) {
  for (const [input, details] of Object.entries(output.inputs)) {
    if (!details.bytesInOutput) continue;
    const name = input.replaceAll('\\', '/');
    const matches = [...name.matchAll(/(?:^|\/)node_modules\/((?:@[^/]+\/)?[^/]+)/g)];
    const match = matches.at(-1);
    if (match) packages.add(name.slice(0, match.index + match[0].length));
  }
}
const notices = [
  await readFile('../NOTICE.md', 'utf8'),
  await readFile('../LICENSE', 'utf8'),
  await readFile('../LICENSING.md', 'utf8'),
  await readFile('components/ReactBits-LICENSE.md', 'utf8'),
  'Manrope variable font - SIL Open Font License 1.1\n' + await readFile('fonts/Manrope-OFL.txt', 'utf8'),
];
for (const directory of [...packages].sort()) {
  const manifest = JSON.parse(await readFile(directory + '/package.json', 'utf8'));
  const files = (await readdir(directory))
    .filter(name => /^(licen[sc]e|copying|notice)(?:[._-].*)?$/i.test(name)).sort();
  if (!files.length) {
    const name = manifest.name.replaceAll('/', '-') + '-' + manifest.version;
    const content = await readFile('licenses/' + name + '.txt', 'utf8');
    notices.push(manifest.name + ' ' + manifest.version + ' - upstream license\n' + content);
  }
  for (const file of files) {
    const content = await readFile(directory + '/' + file, 'utf8');
    notices.push(manifest.name + ' ' + manifest.version + ' - ' + file + '\n' + content);
  }
}
const notice = notices.join('\n\n').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
await mkdir('dist', { recursive: true });
await writeFile('dist/index.html', `<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'sha256-${hash}'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'; object-src 'none'">
<title>FetchVolt</title><style>${css}</style></head><body><template id="third-party-notices"><pre>${notice}</pre></template><div id="root"></div><script>${js}</script></body></html>`);
