#!/usr/bin/env node
// Checks ae/Seaglass.jsx without After Effects: runs it against a strict mock of the AE
// scripting DOM, renders the recorded project with AE's layer rules, and compares it with
// index.html frame by frame (both without motion blur).
//
//   node ae/verify.mjs               every 3rd frame
//   node ae/verify.mjs --all         all 900 frames
//   node ae/verify.mjs --frames 0,75,420 --diff out/ae-diff

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { runJsx } from './mock-ae.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return acc;
}, []));

const proj = runJsx(path.join(HERE, 'Seaglass.jsx'));
const layers = proj.comps.reduce((a, c) => a + c.layers.length, 0);
console.log(`mock AE: ${proj.comps.length} comps, ${layers} layers, engine ${proj.expressionEngine}, ${proj.bitsPerChannel} bpc`);
for (const l of proj.log) console.log('  ' + l);

const frames = args.frames ? String(args.frames).split(',').map(Number)
  : Array.from({ length: 900 }, (_, i) => i).filter(i => args.all || i % 3 === 0);
const diffDir = args.diff ? path.resolve(args.diff) : null;
if (diffDir) fs.mkdirSync(diffDir, { recursive: true });

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript' };
const srv = await new Promise(res => {
  const s = http.createServer((req, rsp) => {
    const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { rsp.writeHead(404); rsp.end(); return; }
    rsp.writeHead(200, { 'content-type': MIME[path.extname(p)] || 'application/octet-stream' });
    fs.createReadStream(p).pipe(rsp);
  }).listen(0, '127.0.0.1', () => res(s));
});
const port = srv.address().port;
const browser = await chromium.launch({ args: ['--disable-gpu', '--force-color-profile=srgb'] });
const orig = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await orig.goto(`http://127.0.0.1:${port}/index.html?render`);
await orig.evaluate(() => window.__ready);
const ae = await browser.newPage();
ae.on('pageerror', e => console.error('[render error]', e.message));
await ae.goto(`http://127.0.0.1:${port}/ae/verify-render.js`);   // same origin, then inject
await ae.setContent('<!doctype html><title>verify</title>');
await ae.addScriptTag({ path: path.join(HERE, 'verify-render.js') });
await ae.evaluate(j => window.__load(j), JSON.stringify(proj));

const results = [];
for (const fi of frames) {
  const url = await orig.evaluate(f => window.__frame(f, 1), fi);
  const r = await ae.evaluate(([f, u, d]) => window.__compare(f, u, d), [fi, url, !!diffDir]);
  if (diffDir) {
    fs.writeFileSync(path.join(diffDir, `ae_${String(fi).padStart(4, '0')}.png`), Buffer.from(r.ae.split(',')[1], 'base64'));
    fs.writeFileSync(path.join(diffDir, `diff_${String(fi).padStart(4, '0')}.png`), Buffer.from(r.diff.split(',')[1], 'base64'));
    fs.writeFileSync(path.join(diffDir, `orig_${String(fi).padStart(4, '0')}.png`), Buffer.from(url.split(',')[1], 'base64'));
    delete r.ae; delete r.diff;
  }
  results.push(r);
}
await browser.close(); srv.close();

const NAMES = ['SUN', 'BEACH', 'WAVE', 'SKY', 'RIPPLE', 'SUNCATCHER', 'CHIME', 'DEEP', 'SAIL', 'WIND', 'GLINT', 'FINALE'];
console.log('scene        frames  mean|diff|   worst frame (mean, >32 levels, max)');
for (let s = 0; s < 12; s++) {
  const rs = results.filter(r => Math.floor(r.fi / 75) === s); if (!rs.length) continue;
  const w = rs.reduce((a, b) => b.mean > a.mean ? b : a);
  console.log(`${String(s + 1).padStart(2)} ${NAMES[s].padEnd(11)} ${String(rs.length).padStart(4)}   ${(rs.reduce((a, b) => a + b.mean, 0) / rs.length).toFixed(3).padStart(8)}     #${w.fi} (${w.mean.toFixed(3)}, ${(w.over * 100).toFixed(3)}%, ${w.max})`);
}
const all = results.reduce((a, b) => a + b.mean, 0) / results.length;
const worst = results.reduce((a, b) => b.over > a.over ? b : a);
console.log(`overall mean |diff| ${all.toFixed(3)} of 255; worst share of pixels off by >32 levels: ${(worst.over * 100).toFixed(3)}% (frame ${worst.fi})`);
if (args.json) fs.writeFileSync(path.resolve(args.json), JSON.stringify(results));
