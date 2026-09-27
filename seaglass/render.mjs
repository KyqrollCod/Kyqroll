#!/usr/bin/env node
// Renders seaglass/index.html to a seamless 1920×1080 / 60p loop with its soundtrack.
//
//   node render.mjs                       full render → out/seaglass.mp4
//   node render.mjs --stills 120,300,480  render a few frames → out/stills/*.png + contact sheet
//   node render.mjs --workers 4 --crf 17
//
// Needs Playwright's Chromium and an ffmpeg build with libx264 (set FFMPEG=/path/to/ffmpeg).

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return acc;
}, []));
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const OUT = path.resolve(args.out || path.join(ROOT, 'out'));
const WORKERS = +(args.workers || 4);
const CRF = String(args.crf || 18);
const SUB = args.sub ? +args.sub : null;       // force subframe count (default: per-frame from page)
const FRAMES = 900, FPS = 60;

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.woff2': 'font/woff2', '.css': 'text/css' };
function serve() {
  return new Promise(res => {
    const srv = http.createServer((req, rsp) => {
      const p = path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
      if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { rsp.writeHead(404); rsp.end(); return; }
      rsp.writeHead(200, { 'content-type': MIME[path.extname(p)] || 'application/octet-stream' });
      fs.createReadStream(p).pipe(rsp);
    }).listen(0, '127.0.0.1', () => res(srv));
  });
}

async function openPage(browser, port) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('pageerror', e => console.error('[page error]', e.message));
  page.on('console', m => { if (m.type() === 'error') console.error('[console]', m.text()); });
  await page.goto(`http://127.0.0.1:${port}/index.html?render`);
  const info = await page.evaluate(() => window.__ready);
  if (info.missing.length) throw new Error('Fonts failed to load: ' + info.missing.join(', '));
  return page;
}

function run(cmd, argv) {
  return new Promise((res, rej) => {
    const p = spawn(cmd, argv, { stdio: ['ignore', 'inherit', 'inherit'] });
    p.on('exit', code => code === 0 ? res() : rej(new Error(`${cmd} exited ${code}`)));
  });
}

function writeWav(file, b64, rate) {
  const pcm = Buffer.from(b64, 'base64');
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + pcm.length, 4); h.write('WAVE', 8);
  h.write('fmt ', 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(2, 22);
  h.writeUInt32LE(rate, 24); h.writeUInt32LE(rate * 4, 28); h.writeUInt16LE(4, 32); h.writeUInt16LE(16, 34);
  h.write('data', 36); h.writeUInt32LE(pcm.length, 40);
  fs.writeFileSync(file, Buffer.concat([h, pcm]));
}

async function main() {
  const srv = await serve();
  const port = srv.address().port;
  const launch = () => chromium.launch({ args: ['--disable-gpu', '--font-render-hinting=none', '--force-color-profile=srgb'] });

  if (args.stills) {
    const list = String(args.stills).split(',').map(Number);
    const dir = path.join(OUT, 'stills'); fs.mkdirSync(dir, { recursive: true });
    const browser = await launch(); const page = await openPage(browser, port);
    for (const fi of list) {
      const url = await page.evaluate(([f, n]) => window.__frame(f, n), [fi, SUB ?? 1]);
      fs.writeFileSync(path.join(dir, `s_${String(fi).padStart(4, '0')}.png`), Buffer.from(url.split(',')[1], 'base64'));
    }
    await browser.close(); srv.close();
    if (list.length > 1) {
      const cols = Math.min(4, list.length), rows = Math.ceil(list.length / cols);
      await run(FFMPEG, ['-y', '-loglevel', 'error', '-pattern_type', 'glob', '-i', path.join(dir, 's_*.png'),
        '-vf', `scale=480:-1,tile=${cols}x${rows}:padding=6:color=0x333333`, '-frames:v', '1', path.join(dir, 'sheet.png')]);
    }
    console.log('stills →', dir);
    return;
  }

  const framesDir = path.join(OUT, 'frames'); fs.mkdirSync(framesDir, { recursive: true });
  const t0 = Date.now();
  const first = +(args.from || 0), last = +(args.to || FRAMES - 1);
  const todo = []; for (let f = first; f <= last; f++) todo.push(f);
  let done = 0;
  const workers = Array.from({ length: WORKERS }, async (_, w) => {
    const browser = await launch(); const page = await openPage(browser, port);
    if (w === 0 && !args['no-audio']) {
      const a = await page.evaluate(() => window.__audio());
      writeWav(path.join(OUT, 'audio.wav'), a.b64, a.rate);
      console.log(`audio: ${a.frames} samples @ ${a.rate} Hz, raw peak ${a.peak.toFixed(3)}, raw rms ${a.rms.toFixed(3)}`);
    }
    while (todo.length) {
      const fi = todo.shift();
      const url = await page.evaluate(([f, n]) => window.__frame(f, n), [fi, SUB]);
      fs.writeFileSync(path.join(framesDir, `f_${String(fi).padStart(4, '0')}.png`), Buffer.from(url.split(',')[1], 'base64'));
      if (++done % 50 === 0) console.log(`${done}/${last - first + 1} frames · ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    await browser.close();
  });
  await Promise.all(workers);
  srv.close();
  console.log(`frames done in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  if (args['no-encode']) return;

  const mp4 = path.join(OUT, 'seaglass.mp4');
  await run(FFMPEG, ['-y', '-loglevel', 'error', '-stats',
    '-framerate', String(FPS), '-i', path.join(framesDir, 'f_%04d.png'),
    '-i', path.join(OUT, 'audio.wav'),
    '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', CRF, '-profile:v', 'high', '-g', '120',
    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
    '-c:a', 'aac', '-b:a', '320k', '-shortest', '-movflags', '+faststart', mp4]);
  console.log('video →', mp4);
}

main().catch(e => { console.error(e); process.exit(1); });
