#!/usr/bin/env node
// Renders clear-horizon/index.html to a seamless 1920×1080 / 60p loop with its soundtrack.
//
//   node render.mjs                       full render → out/clear-horizon.mp4
//   node render.mjs --stills 120,300,480  render a few frames → out/stills/*.png + contact sheet
//   node render.mjs --workers 4 --crf 17
//   node render.mjs --hud                  include the HUD overlay (timecode, bar/beat, altitude gauge)
//   node render.mjs --ae                   After Effects kit: 12 layer passes with alpha (ProRes 4444) in
//                                          ae/passes/, soundtrack + stems in ae/audio/, ae/ClearHorizon.jsx
//   node render.mjs --ae --ae-png          same, but keep the passes as PNG sequences
//                                          (--ae also writes the light kit in ae/lite/: each pass as an H.264 fill
//                                          plus a luma matte, small enough to keep in the repository)
//   node render.mjs --ae --ae-reuse        re-encode from the pass frames already in out/ae-frames
//   node render.mjs --ae --ae-lite-only    only the light kit (no ProRes / PNG passes)
//   node render.mjs --ae --ae-jsx-only     only rewrite ae/ClearHorizon.jsx
//   node render.mjs --prores               also write a ProRes 422 HQ master → out/clear-horizon-prores.mov
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
  await page.goto(`http://127.0.0.1:${port}/index.html?render${args.hud ? '&hud' : ''}`);
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

  if (args.ae) { await renderAE(port, launch); srv.close(); return; }

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

  const mp4 = path.join(OUT, 'clear-horizon.mp4');
  await run(FFMPEG, ['-y', '-loglevel', 'error', '-stats',
    '-framerate', String(FPS), '-i', path.join(framesDir, 'f_%04d.png'),
    '-i', path.join(OUT, 'audio.wav'),
    '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', CRF, '-profile:v', 'high', '-g', '120',
    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
    '-c:a', 'aac', '-b:a', '320k', '-shortest', '-movflags', '+faststart', mp4]);
  console.log('video →', mp4);
  if (args.prores) {
    const mov = path.join(OUT, 'clear-horizon-prores.mov');
    await run(FFMPEG, ['-y', '-loglevel', 'error', '-stats',
      '-framerate', String(FPS), '-i', path.join(framesDir, 'f_%04d.png'), '-i', path.join(OUT, 'audio.wav'),
      '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv422p10le',
      '-c:v', 'prores_ks', '-profile:v', '3', '-vendor', 'apl0',
      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
      '-c:a', 'pcm_s16le', '-shortest', mov]);
    console.log('ProRes master →', mov);
  }
}

/* ------------------------------------------------------------------ *
 *  After Effects kit: every element group rendered on transparency with
 *  the same motion blur, so stacking the passes rebuilds the frame.
 * ------------------------------------------------------------------ */
const PASS_NAMES = {
  sky: 'Sky + sun', clouds: 'Clouds', birds: 'Birds', sea: 'Sea (dot field)', glitter: 'Sun glitter', speed: 'Speed lines',
  motes: 'Wind motes', wind: 'Wind ribbons', under: 'Underwater', 'under-life': 'Underwater currents, fish, bubbles',
  waterline: 'Waterline', splash: 'Splash'
};
async function renderAE(port, launch) {
  const aeDir = path.join(ROOT, 'ae'), passDir = path.join(aeDir, 'passes'), audioDir = path.join(aeDir, 'audio');
  const tmp = path.join(OUT, 'ae-frames');
  fs.mkdirSync(passDir, { recursive: true }); fs.mkdirSync(path.join(audioDir, 'stems'), { recursive: true });
  const t0 = Date.now();
  let passes = null, events = null;
  const reuse = (args['ae-reuse'] && fs.existsSync(tmp)) || args['ae-jsx-only'];
  const todo = reuse ? [] : Array.from({ length: FRAMES }, (_, i) => i);
  let done = 0;
  await Promise.all(Array.from({ length: WORKERS }, async (_, w) => {
    const browser = await launch(); const page = await openPage(browser, port);
    if (w === 0) {
      passes = await page.evaluate(() => window.__passes());
      events = await page.evaluate(() => window.__events());
    }
    if (w === 0 && !reuse) {
      const mix = await page.evaluate(() => window.__audio());
      writeWav(path.join(audioDir, 'clear-horizon.wav'), mix.b64, mix.rate);
      for (const stem of ['drums', 'bass', 'music', 'fx']) {
        const a = await page.evaluate(([s, g]) => window.__audio(s, g), [stem, mix.gain]);
        writeWav(path.join(audioDir, 'stems', `clear-horizon-${stem}.wav`), a.b64, a.rate);
      }
      console.log('audio →', audioDir);
    } else while (!passes) await new Promise(r => setTimeout(r, 50));
    const dirs = passes.map((p, i) => path.join(tmp, `${String(i + 1).padStart(2, '0')}_${p}`));
    dirs.forEach(d => fs.mkdirSync(d, { recursive: true }));
    while (todo.length) {
      const fi = todo.shift();
      const urls = await page.evaluate(([f, n]) => window.__framePasses(f, n), [fi, SUB ?? 6]);
      urls.forEach((u, i) => fs.writeFileSync(path.join(dirs[i], `${path.basename(dirs[i])}_${String(fi).padStart(4, '0')}.png`), Buffer.from(u.split(',')[1], 'base64')));
      if (++done % 50 === 0) console.log(`${done}/${FRAMES} frames × ${passes.length} passes · ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    await browser.close();
  }));
  const names = passes.map((p, i) => `${String(i + 1).padStart(2, '0')}_${p}`);
  if (!args['ae-jsx-only']) await encodeLite(tmp, names, path.join(aeDir, 'lite'));
  for (const n of args['ae-lite-only'] || args['ae-jsx-only'] ? [] : names) {
    if (args['ae-png']) {
      fs.rmSync(path.join(passDir, n), { recursive: true, force: true });
      fs.renameSync(path.join(tmp, n), path.join(passDir, n));
      continue;
    }
    await run(FFMPEG, ['-y', '-loglevel', 'error',
      '-framerate', String(FPS), '-i', path.join(tmp, n, `${n}_%04d.png`),
      '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le',
      '-c:v', 'prores_ks', '-profile:v', '4', '-alpha_bits', '16', '-vendor', 'apl0',
      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
      path.join(passDir, `${n}.mov`)]);
    console.log(`pass ${n}.mov: ${(fs.statSync(path.join(passDir, `${n}.mov`)).size / 1048576).toFixed(1)} MB`);
  }
  const markers = [...Array.from({ length: 6 }, (_, b) => [b * events.bar, `bar ${b + 1}`]), [events.dive, 'DIVE'], [events.breach, 'BREACH']].sort((a, b) => a[0] - b[0]);
  fs.writeFileSync(path.join(aeDir, 'ClearHorizon.jsx'), aeJsx(passes.map((p, i) => [names[i], PASS_NAMES[p] || p]), markers));
  console.log(`After Effects kit → ${aeDir} (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
}

// The light kit: H.264 is small but has no alpha, so each pass becomes a colour "fill" (straight
// colour; transparent pixels white, since most of these elements are white) and a greyscale luma matte.
// The sky pass is opaque and needs no matte. ClearHorizon.jsx wires them up as track mattes.
async function encodeLite(tmp, names, dir) {
  fs.mkdirSync(dir, { recursive: true });
  const tags = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv'];
  const jobs = names.map(n => () => {
    const opaque = n.endsWith('_sky');
    const input = ['-framerate', String(FPS), '-i', path.join(tmp, n, `${n}_%04d.png`)];
    const fill = `[0]format=rgba,split[c][m];[c]geq=r='if(gt(alpha(X,Y),0),r(X,Y),255)':g='if(gt(alpha(X,Y),0),g(X,Y),255)':b='if(gt(alpha(X,Y),0),b(X,Y),255)',scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[fill];[m]alphaextract,format=gray,scale=out_range=tv,format=yuv420p[matte]`;
    const x264 = crf => ['-c:v', 'libx264', '-preset', 'slow', '-crf', String(crf), '-profile:v', 'high', '-g', '120', ...tags, '-movflags', '+faststart'];
    return opaque
      ? run(FFMPEG, ['-y', '-loglevel', 'error', ...input, '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p', ...x264(16), path.join(dir, `${n}_fill.mp4`)])
      : run(FFMPEG, ['-y', '-loglevel', 'error', ...input, '-filter_complex', fill,
          '-map', '[fill]', ...x264(16), path.join(dir, `${n}_fill.mp4`), '-map', '[matte]', ...x264(12), path.join(dir, `${n}_matte.mp4`)]);
  });
  const queue = [...jobs];
  await Promise.all(Array.from({ length: 4 }, async () => { while (queue.length) await queue.shift()(); }));
  let total = 0;
  for (const f of fs.readdirSync(dir)) total += fs.statSync(path.join(dir, f)).size;
  console.log(`light kit → ${dir} (${(total / 1048576).toFixed(1)} MB)`);
}

function aeJsx(passes, markers) {
  return `// Clear Horizon: After Effects project builder (generated by render.mjs --ae; rebuild instead of editing)
//
// In After Effects: File > Scripts > Run Script File... and choose this file. It builds a
// "Clear Horizon" folder with a 15 s comp (1920x1080, 60 fps) that stacks the ${passes.length} layer passes in
// order (stacked, they rebuild the finished frame), the soundtrack and stems from ae/audio/, bar and
// dive/breach markers, and ../clear-horizon.mp4 as a guide layer.
// Each pass comes from the best source present: ae/passes/NN_name.mov (ProRes 4444 with alpha), then
// ae/passes/NN_name/ (PNG sequence), then the light kit in ae/lite/ (H.264 fill + luma track matte).
// The full-quality passes are large, so they are not in the repository: make them with  node render.mjs --ae
(function () {
  var PASSES = ${JSON.stringify(passes)};
  var MARKERS = ${JSON.stringify(markers.map(([t, n]) => [+t.toFixed(6), n]))};
  var STEMS = ["drums", "bass", "music", "fx"];
  var BASE = new File($.fileName).parent;

  function importFile(f, folder, seq) {
    var io = new ImportOptions(f);
    if (seq) { io.sequence = true; io.forceAlphabetical = true; }
    var item = app.project.importFile(io);
    if (folder) item.parentFolder = folder;
    return item;
  }
  function pass(name, folder) {
    var mov = new File(BASE.fsName + "/passes/" + name + ".mov");
    if (mov.exists) return { item: importFile(mov, folder, false) };
    var dir = new Folder(BASE.fsName + "/passes/" + name);
    var files = dir.exists ? dir.getFiles("*.png") : [];
    if (files.length) {
      files.sort(function (a, b) { return a.name < b.name ? -1 : 1; });
      return { item: importFile(files[0], folder, true) };
    }
    var fill = new File(BASE.fsName + "/lite/" + name + "_fill.mp4"), matte = new File(BASE.fsName + "/lite/" + name + "_matte.mp4");
    if (!fill.exists) return null;
    return { item: importFile(fill, folder, false), matte: matte.exists ? importFile(matte, folder, false) : null, lite: true };
  }

  app.beginUndoGroup("Build Clear Horizon");
  try {
    if (!app.project) app.newProject();
    try { app.project.bitsPerChannel = 16; } catch (e1) {}
    var root = app.project.items.addFolder("Clear Horizon");
    var passFolder = app.project.items.addFolder("Passes"); passFolder.parentFolder = root;
    var audioFolder = app.project.items.addFolder("Audio"); audioFolder.parentFolder = root;
    var comp = app.project.items.addComp("Clear Horizon", 1920, 1080, 1, 15, 60);
    comp.parentFolder = root;
    comp.bgColor = [0.471, 0.784, 0.973];
    var missing = [], lite = 0, i, L, f;
    for (i = 0; i < PASSES.length; i++) {           // bottom to top: AE adds each new layer on top
      var src = pass(PASSES[i][0], passFolder);
      if (!src) { missing.push(PASSES[i][0]); continue; }
      var label = PASSES[i][0].substr(0, 2) + " " + PASSES[i][1];
      if (src.item.mainSource.hasAlpha) src.item.mainSource.alphaMode = AlphaMode.STRAIGHT;
      src.item.mainSource.conformFrameRate = 60;
      L = comp.layers.add(src.item);
      L.name = label;
      if (src.lite) lite++;
      if (src.matte) {
        // the matte goes directly above its fill; its brightness becomes the fill's alpha
        var M = comp.layers.add(src.matte);
        M.name = label + " (matte)";
        if (typeof L.setTrackMatte === "function") L.setTrackMatte(M, TrackMatteType.LUMA);
        else L.trackMatteType = TrackMatteType.LUMA;
        M.enabled = false;
      }
    }
    f = new File(BASE.fsName + "/audio/clear-horizon.wav");
    if (f.exists) {
      L = comp.layers.add(importFile(f, audioFolder, false));
      L.name = "Soundtrack";
      for (i = 0; i < 24; i++) L.property("ADBE Marker").setValueAtTime(i * 0.625, new MarkerValue(i % 4 ? "" : "bar " + (i / 4 + 1)));
    }
    for (i = 0; i < STEMS.length; i++) {
      f = new File(BASE.fsName + "/audio/stems/clear-horizon-" + STEMS[i] + ".wav");
      if (f.exists) importFile(f, audioFolder, false);
    }
    f = new File(BASE.parent.fsName + "/clear-horizon.mp4");
    if (f.exists) {
      L = comp.layers.add(importFile(f, root, false));
      L.name = "Reference render (guide)";
      L.guideLayer = true; L.enabled = false; if (L.hasAudio) L.audioEnabled = false;
    }
    for (i = 0; i < MARKERS.length; i++) comp.markerProperty.setValueAtTime(MARKERS[i][0], new MarkerValue(MARKERS[i][1]));
    comp.openInViewer();
    if (missing.length) alert("Clear Horizon: " + missing.length + " passes were not found.\\nMake them with:  node render.mjs --ae");
    else if (lite) alert("Clear Horizon: built from the light kit (H.264 fill + luma matte).\\nFor full-quality ProRes 4444 passes run  node render.mjs --ae  and build again.");
  } catch (err) {
    alert("Clear Horizon: the build stopped at line " + err.line + "\\n" + err.toString());
  }
  app.endUndoGroup();
})();
`;
}

main().catch(e => { console.error(e); process.exit(1); });
