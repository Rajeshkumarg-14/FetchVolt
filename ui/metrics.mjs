const units = {
  kbps: ['kbps', bytes => bytes * 8 / 1_000],
  mbps: ['Mbps', bytes => bytes * 8 / 1_000_000],
  mbs: ['MB/s', bytes => bytes / 1_000_000],
  mibs: ['MiB/s', bytes => bytes / 1_048_576],
};

export const speedOptions = [
  ...Object.entries(units).map(([value, [label]]) => ({ value, label })),
  { value: 'auto', label: 'Auto (bits/s)' },
];

export function formatRate(bytesPerSecond, preference) {
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond < 0) return '—';
  if (preference === 'auto' && bytesPerSecond * 8 >= 1_000_000_000) {
    return (bytesPerSecond * 8 / 1_000_000_000).toFixed(2) + ' Gbps';
  }
  const mode = preference === 'auto' ? (bytesPerSecond * 8 < 1_000_000 ? 'kbps' : 'mbps') : preference;
  const [label, convert] = units[mode] ?? units.mbps;
  return convert(bytesPerSecond).toFixed(2) + ' ' + label;
}

export function formatStorage(bytes) {
  const gib = bytes / 1024 ** 3;
  return gib >= 1024 ? (gib / 1024).toFixed(2) + ' TiB' : gib.toFixed(1) + ' GiB';
}
