#!/usr/bin/env node
// Builds Seaglass.jsx: an After Effects script that rebuilds the loop as native, editable layers
// (shape layers, nulls, solids, 12 scene precomps, markers, soundtrack).
//
//   node ae/build.mjs            → ae/Seaglass.jsx
//
// Each scene from index.html is re-expressed as layers whose properties are functions of the
// scene's beat position u. Every function is sampled once per frame and reduced to the fewest
// linear keyframes that stay within a fraction of a pixel of the original curve; motion that is
// procedural by nature (streams that wrap around, swinging wave lines) becomes a short expression
// instead. ae/verify.mjs renders the result back through a mock of the AE object model and
// compares it with the canvas original frame by frame.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

const W = 1920, H = 1080, FPS = 60, L = 15;
const BPM = 96, BEAT = 60 / BPM, SCENE = 2 * BEAT, SF = Math.round(SCENE * FPS);   // 75 frames per scene
const TAU = Math.PI * 2, CX = W / 2, CY = H / 2;

const P = {
  bg: '#F7FCFF', white: '#FFFFFF', azure: '#2E9CF0', turq: '#3BD0E9', deep: '#1D6FD1', deeper: '#1350B9',
  aqua: '#A5F0F4', lav: '#B8B0F5', sun: '#FFE58A', pink: '#F7CADD'
};

/* ------------------------------------------------------------------ *
 *  Helpers (identical to index.html)
 * ------------------------------------------------------------------ */
const frac = x => x - Math.floor(x);
const clamp = (x, a = 0, b = 1) => x < a ? a : x > b ? b : x;
const lerp = (a, b, t) => a + (b - a) * t;
const prog = (a, b, x) => clamp((x - a) / (b - a));
const inCubic = t => t * t * t;
const outCubic = t => 1 - Math.pow(1 - t, 3);
const outExpo = t => t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);
const inOutCubic = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const outBack = (t, s = 1.9) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2);
const pop = (u, t0, d = .24) => { const p = prog(t0, t0 + d, u); return p <= 0 ? 0 : outBack(p); };
const hash = n => frac(Math.sin(n * 127.1 + 311.7) * 43758.5453);
function rng(seed) {
  return () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
const pick = (r, list) => { let s = 0; for (const [, w] of list) s += w; let x = r() * s; for (const [v, w] of list) { if ((x -= w) <= 0) return v; } return list[0][0]; };
const pad2 = n => String(n).padStart(2, '0');

const TYPES = [['circle', 26], ['crescent', 16], ['gem', 11], ['nested', 7], ['plus', 10], ['star', 6], ['tri', 9], ['wave', 8], ['dots', 7], ['ring', 7], ['half', 5]];
function makeCollage(seed, n, cols) {
  const r = rng(seed), items = [];
  const gc = Math.ceil(Math.sqrt(n * W / H)), gr = Math.ceil(n / gc);
  for (let i = 0; i < n; i++) {
    const gx = (i % gc + .5 + (r() - .5) * .95) / gc, gy = (Math.floor(i / gc) + .5 + (r() - .5) * .95) / gr;
    const x = -180 + gx * (W + 360), y = -140 + gy * (H + 280);
    const q = r(), s = q < .16 ? 120 + r() * 150 : q < .6 ? 44 + r() * 70 : 12 + r() * 26;
    const col = pick(r, cols), col2 = pick(r, cols);
    items.push({ type: pick(r, TYPES), x, y, s, rot: r() * TAU, spin: (r() - .5) * 2.2, col, col2: col2 === col ? P.white : col2,
      mul: r() < .55, layer: r(), t0: .02 + Math.hypot(x - W / 2, y - H / 2) / 1100 * .3, ph: r() * TAU });
  }
  return items.sort((a, b) => b.s - a.s);
}
const LIGHT = [[P.azure, 5], [P.turq, 6], [P.deep, 3], [P.aqua, 5], [P.lav, 5], [P.sun, 2]];
const COLLAGE_BEACH = makeCollage(11, 96, LIGHT);
const COLLAGE_FINALE = makeCollage(29, 96, LIGHT);
const COLLAGE_DEEP = makeCollage(47, 70, [[P.aqua, 5], [P.turq, 5], [P.lav, 4], [P.white, 4], [P.azure, 2]]);

/* ------------------------------------------------------------------ *
 *  Geometry → AE shape items. Paths are {v, i, o, closed} with
 *  tangents relative to their vertex, exactly as AE's Shape object.
 * ------------------------------------------------------------------ */
const Z2 = [0, 0];
const poly = (pts, closed = true) => ({ v: pts, i: pts.map(() => Z2), o: pts.map(() => Z2), closed });
function arcSegs(cx, cy, r, a0, a1, n) {                // circular arc as n cubic segments
  const segs = [], d = (a1 - a0) / n, h = 4 / 3 * Math.tan(d / 4) * r;
  for (let k = 0; k < n; k++) {
    const t0 = a0 + k * d, t1 = t0 + d;
    const p0 = [cx + r * Math.cos(t0), cy + r * Math.sin(t0)], p3 = [cx + r * Math.cos(t1), cy + r * Math.sin(t1)];
    segs.push([p0, [p0[0] - h * Math.sin(t0), p0[1] + h * Math.cos(t0)], [p3[0] + h * Math.sin(t1), p3[1] - h * Math.cos(t1)], p3]);
  }
  return segs;
}
const lineSeg = (a, b) => [a, a, b, b];
function segsToPath(segs, closed) {
  const v = [], i = [], o = [];
  segs.forEach((s, k) => {
    v.push(s[0]); o.push([s[1][0] - s[0][0], s[1][1] - s[0][1]]);
    i.push(k === 0 ? Z2 : [segs[k - 1][2][0] - s[0][0], segs[k - 1][2][1] - s[0][1]]);
  });
  const last = segs[segs.length - 1];
  if (closed) i[0] = [last[2][0] - last[3][0], last[2][1] - last[3][1]];
  else { v.push(last[3]); i.push([last[2][0] - last[3][0], last[2][1] - last[3][1]]); o.push(Z2); }
  return { v, i, o, closed };
}
// circle r minus the circle of radius .9r whose centre sits cut·r along +x (canvas crescent() at angle 0)
function crescentPath(r, cut) {
  const d = cut * r, rb = .9 * r;
  const x = (d * d + r * r - rb * rb) / (2 * d), y = Math.sqrt(r * r - x * x);
  const a = Math.atan2(y, x), b = Math.atan2(y, x - d);
  return segsToPath([...arcSegs(0, 0, r, a, TAU - a, 6), ...arcSegs(d, 0, rb, TAU - b, b, 4)], true);
}
const halfPath = r => segsToPath([...arcSegs(0, 0, r, Math.PI, TAU, 2), lineSeg([r, 0], [-r, 0])], true);
const diamond = q => [[0, -q], [q, 0], [0, q], [-q, 0]];
const starPts = (r, pinch) => Array.from({ length: 8 }, (_, k) => { const a = k * Math.PI / 4 - Math.PI / 2, rr = k % 2 ? r * pinch : r; return [Math.cos(a) * rr, Math.sin(a) * rr]; });
const triPts = s => [[0, -s], [s * .87, s * .5], [-s * .87, s * .5]];
const leafPath = segsToPath([[[0, -46], [30, -10], [34, 24], [0, 46]], [[0, 46], [-34, 24], [-30, -10], [0, -46]]], true);

// an open curve sampled finely, plus a map from curve parameter to Trim Paths percentage
function trimmable(curve, n = 240) {
  const pts = [], acc = [0];
  for (let k = 0; k <= n; k++) { pts.push(curve(k / n)); if (k) acc.push(acc[k - 1] + Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])); }
  const total = acc[n];
  const at = q => { const x = clamp(q) * n, k = Math.min(n - 1, Math.floor(x)); return lerp(acc[k], acc[k + 1], x - k) / total; };
  return { path: poly(pts, false), at };
}

// item constructors (values may be constants or functions of u)
const ELL = (d, c) => ({ ell: { d, c } });
const RECT = (size, c, round = 0) => ({ rect: { size, c, round } });
const PATH = p => ({ path: p });
const FILL = (c, o = 1, rule) => ({ fill: { c, o, rule } });
const STROKE = (c, w, o = 1, cap = 'butt', join = 'miter') => ({ stroke: { c, w, o, cap, join } });
const TRIM = (s, e) => ({ trim: { s, e } });
const plusItems = s => { const w = s * .34; return [RECT([2 * s, w], Z2, w / 2), RECT([w, 2 * s], Z2, w / 2)]; };
const gemGroups = (s, a, b) => [
  { name: 'Left facet', items: [PATH(poly([[0, -s], [0, s], [-s * .78, 0]])), FILL(a)] },
  { name: 'Right facet', items: [PATH(poly([[0, -s], [s * .78, 0], [0, s]])), FILL(b)] },
  { name: 'Highlight', items: [PATH(poly([[-s * .18, -s * .5], [0, -s * .72], [s * .18, -s * .5], [0, -s * .28]])), FILL(P.white, .85)] }
];

/* ------------------------------------------------------------------ *
 *  Expressions: short, exact, and still readable in the timeline.
 *  ex(code, fn) keeps a JS twin so the build can check every frame.
 * ------------------------------------------------------------------ */
const ex = (code, fn) => ({ __ex: true, code, fn });
const n = x => JSON.stringify(+x);
const U = 'var u = (time - thisLayer.startTime) / 0.625;';
const streamExpr = (h0, v, x0, span, y) => [U,
  `var f = ${n(h0)} + u * ${n(v)}; f = f - Math.floor(f);`,
  `[${n(x0)} + f * ${n(span)}, ${n(y)}]`].join('\n');
const wrapXYExpr = (h1, vx, sx, ox, h2, vy, sy) => [U,
  `var fx = ${n(h1)} + u * ${n(vx)}, fy = ${n(h2)} + u * ${n(vy)};`,
  `[(fx - Math.floor(fx)) * ${n(sx)} + ${n(ox)}, (fy - Math.floor(fy)) * ${n(sy)}]`].join('\n');
const waveExpr = (s, ph0) => [U,
  `var s = ${n(s)}, ph = ${n(ph0)} + u * 5, p = [];`,
  `for (var i = 0; i <= 36; i++) { var q = i / 36; p.push([-s * 1.4 + 2.8 * s * q, Math.sin(q * Math.PI * 2 * 1.5 + ph) * s * 0.26]); }`,
  `createPath(p, [], [], false)`].join('\n');
const birdExpr = (sz, o) => [U,
  `var a = 0.25 + 0.4 * Math.abs(Math.sin((u + ${n(o)}) * Math.PI * 3)), s = ${n(sz)};`,
  `createPath([[-s, -s * a], [0, 0], [s, -s * a]], [], [], false)`].join('\n');
const swellExpr = (dx, dy) => [U,
  `var p = Math.min(Math.max(u / 0.5, 0), 1), d = p >= 1 ? 1 : 1 - Math.pow(2, -10 * p);`,
  `var x0 = 960 - 1100 * d, x1 = 960 + 1100 * d, k = Math.PI * 2 / 900, pts = [];`,
  `for (var x = x0; x <= x1; x += 20) pts.push([x, 690 + Math.sin((x - ${n(dx)}) * k - u * 3.2) * 44 + ${n(dy)}]);`,
  `createPath(pts, [], [], false)`].join('\n');

/* ------------------------------------------------------------------ *
 *  Scene model. Layers are listed bottom → top, groups within a layer
 *  bottom → top (canvas drawing order); the emitter reverses them into
 *  AE's top-first order.
 * ------------------------------------------------------------------ */
let uid = 0;
class Scene {
  constructor(name) { this.name = name; this.layers = []; }
  add(kind, spec) { const l = { id: ++uid, kind, ...spec }; this.layers.push(l); return l; }
  shape(spec) { return this.add('shape', spec); }
  null(spec) { return this.add('null', spec); }
  solid(spec) { return this.add('solid', spec); }
}
const bgSolid = (S, col, name = 'Background') => S.solid({ name, color: col, w: W, h: H, a: [W / 2, H / 2], p: [CX, CY], label: 16 });
const zoomNull = (S, z) => S.null({ name: 'Zoom', a: [CX, CY], p: [CX, CY], s: z });
const ramp = (sp, sc, ep, ec) => ({ m: 'ADBE Ramp', p: { 'ADBE Ramp-0001': sp, 'ADBE Ramp-0002': rgb4(sc), 'ADBE Ramp-0003': ep, 'ADBE Ramp-0004': rgb4(ec), 'ADBE Ramp-0005': 1 } });

function trioLayers(S, orbitR, rot, r, vis) {
  const F = v => typeof v === 'function' ? v : () => v;
  const R = F(orbitR), A = F(rot), Rad = F(r);
  const at = (u, k) => { const a = A(u) + k * TAU / 3; return [CX + Math.cos(a) * R(u), CY + Math.sin(a) * R(u)]; };
  S.shape({ name: 'Aqua disc', blend: 'multiply', vis, p: u => at(u, 1), s: u => Rad(u) / 150, groups: [{ name: 'Disc', items: [ELL(300), FILL(P.aqua)] }] });
  S.shape({ name: 'Lavender disc', blend: 'multiply', vis, p: u => at(u, 2), s: u => Rad(u) / 150, groups: [{ name: 'Disc', items: [ELL(300), FILL(P.lav)] }] });
  S.shape({ name: 'Sun disc', vis, o: .92, p: u => at(u, 0), s: u => Rad(u) / 150, groups: [{ name: 'Disc', items: [ELL(246), FILL(P.sun)] }] });
}

// A collage burst: one layer per shape (plus an extra layer for each further colour of a
// multiplied shape, since multiply has to act colour by colour to match the canvas).
function collageLayers(S, items, o) {
  const pan = o.pan, mul = o.mul !== false;
  items.forEach((it, idx) => {
    const conv = u => o.converge != null ? inCubic(prog(o.converge + it.layer * .15, o.converge + .55 + it.layer * .15, u)) : 0;
    const vis = u => { const sc = pop(u, it.t0); return sc > 0 && (o.converge == null || sc * (1 - conv(u)) > .001); };
    const scale = u => { const sc = pop(u, it.t0); return sc <= 0 ? 0 : sc * (1 - conv(u)); };
    const pos = u => {
      const x = it.x + pan[0] * (.6 + .8 * it.layer) * u, y = it.y + pan[1] * (.6 + .8 * it.layer) * u, k = conv(u);
      return [lerp(x, CX, k), lerp(y, CY, k)];
    };
    const R = u => it.rot + it.spin * u;
    const isMul = mul && it.mul && it.col !== P.sun;
    const name = `${pad2(idx + 1)} ${it.type}`, s = it.s;
    const base = { name, vis, p: pos, s: scale, parent: o.parent, blend: isMul ? 'multiply' : 'normal', label: isMul ? 5 : 8 };
    const one = (r, items2) => S.shape({ ...base, r, groups: [{ name: it.type[0].toUpperCase() + it.type.slice(1), items: items2 }] });
    switch (it.type) {
      case 'circle': one(0, [ELL(2 * s), FILL(it.col)]); break;
      case 'crescent': one(R, [PATH(crescentPath(s, .45 + .2 * Math.sin(it.ph))), FILL(it.col)]); break;
      case 'gem': {
        const g = gemGroups(s, it.col, it.col2);
        S.shape({ ...base, r: u => R(u) * .3, groups: isMul ? (it.col2 === P.white ? [g[0]] : [g[0], g[1]]) : g });
        break;
      }
      case 'nested': {
        const r = u => R(u) * .25 + Math.PI / 4, cols = [it.col, P.white, it.col2];
        const dia = k => ({ name: `Diamond ${k + 1}`, items: [PATH(poly(diamond(s * (1 - k / 3)))), FILL(cols[k])] });
        if (!isMul) { S.shape({ ...base, r, groups: [dia(0), dia(1), dia(2)] }); break; }
        let main = null;                                 // white multiplies to nothing, so it is left out
        cols.forEach((col, k) => {
          if (col === P.white) return;
          if (!main) main = S.shape({ ...base, r, groups: [dia(k)] });
          else S.shape({ name: `${name} inner`, parent: main, vis, blend: 'multiply', label: 5, groups: [dia(k)] });
        });
        break;
      }
      case 'plus': one(R, [...plusItems(s * .6), FILL(it.col)]); break;
      case 'star': one(u => R(u) * .5, [PATH(poly(starPts(s * .9, .16))), FILL(it.col)]); break;
      case 'tri': one(R, [PATH(poly(triPts(s * .8))), FILL(it.col)]); break;
      case 'wave': {
        const sw = s * .7;
        const wave = u => poly(Array.from({ length: 37 }, (_, i) => { const q = i / 36; return [-sw * 1.4 + 2.8 * sw * q, Math.sin(q * TAU * 1.5 + it.ph + u * 5) * sw * .26]; }), false);
        one(u => R(u) * .2, [PATH(ex(waveExpr(sw, it.ph), wave)), STROKE(it.col, sw * .22, 1, 'round', 'round')]);
        break;
      }
      case 'dots': {
        const dots = [];
        for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) dots.push(ELL(s * .16, [i * s * .42, j * s * .42]));
        one(u => R(u) * .2, [...dots, FILL(it.col)]);
        break;
      }
      case 'ring': one(0, [ELL(2 * s * .8), STROKE(it.col, s * .2)]); break;
      case 'half': one(u => R(u) * .5, [PATH(halfPath(s)), FILL(it.col)]); break;
    }
  });
}

/* ------------------------------------------------------------------ *
 *  The twelve scenes
 * ------------------------------------------------------------------ */
function sceneSun(S) {
  bgSolid(S, P.bg);
  const k = u => inOutCubic(prog(0, 1.7, u));
  trioLayers(S, u => lerp(96, 16, k(u)), u => -Math.PI / 2 + Math.PI * k(u), u => 150 + 14 * outCubic(prog(1.6, 2, u)));
  const q = u => prog(1.55, 2, u);
  S.shape({ name: 'Ring', vis: u => q(u) > 0, p: [CX, CY], groups: [{ name: 'Ring', items: [
    ELL(u => 2 * (170 + 420 * outCubic(q(u)))), STROKE(P.azure, u => 5 * (1 - q(u)) + 1, u => 1 - q(u))] }] });
  S.shape({ name: 'Pluses', groups: Array.from({ length: 8 }, (_, i) => {
    const a = i * TAU / 8 + .3;
    return { name: `Plus ${i + 1}`, p: [CX + Math.cos(a) * 360, CY + Math.sin(a) * 300], r: a,
      s: u => pop(u, .1 + i * .12) * (1 - prog(1.7, 2, u)) , items: [...plusItems(16), FILL(P.turq)] };
  }) });
}

function sceneBeach(S) {
  bgSolid(S, P.bg);
  const zoom = zoomNull(S, u => 1 + .05 * u);
  collageLayers(S, COLLAGE_BEACH, { pan: [260, -150], parent: zoom });
}

function sceneWave(S) {
  bgSolid(S, P.bg);
  const step = u => outExpo(prog(0, .5, u)) + outExpo(prog(1, 1.5, u));
  const ang = u => -1.2 + step(u) * 1.35, r = u => 250 * pop(u, 0, .3), vis = u => r(u) > 0;
  S.shape({ name: 'Wave shadow', vis, p: [CX + 20, CY + 10], r: u => ang(u) + Math.PI * .9, s: u => r(u) / 250,
    groups: [{ name: 'Crescent', items: [PATH(crescentPath(320, .22)), FILL(P.aqua)] }] });
  S.shape({ name: 'Wave', vis, p: [CX, CY], r: ang, s: u => r(u) / 250,
    groups: [{ name: 'Crescent', items: [PATH(u => crescentPath(250, .35 + .25 * step(u) / 2)), FILL(P.turq)] }] });
  const oa = u => u * Math.PI * 1.6;
  S.shape({ name: 'Deep dot', vis: u => pop(u, .2) > 0, p: u => [CX + Math.cos(oa(u)) * 400, CY + Math.sin(oa(u)) * 190], s: u => pop(u, .2),
    groups: [{ name: 'Dot', items: [ELL(36), FILL(P.deep)] }] });
  S.shape({ name: 'Lavender dot', vis: u => pop(u, .35) > 0, p: u => [CX - Math.cos(oa(u)) * 330, CY - Math.sin(oa(u)) * 160], s: u => pop(u, .35),
    groups: [{ name: 'Dot', items: [ELL(20), FILL(P.lav)] }] });
}

function sceneSky(S) {
  bgSolid(S, P.azure);
  const cols = [P.white, P.aqua, P.turq, P.lav, P.white, P.deep, P.aqua, P.white, P.lav];
  cols.forEach((col, k) => {
    const y = -720 + k * 170 + (k % 2 ? 30 : 0), th = 24 + 70 * hash(k * 3.1), speed = (900 + 1100 * hash(k * 7.3)) * (k % 2 ? 1 : 1.3);
    const groups = [];
    for (let j = -1; j < 5; j++) {
      const len = 260 + 420 * hash(k * 11 + j), h0 = hash(k + j * 5), v = speed / 3200;
      groups.push({ name: `Pill ${j + 2}`, p: ex(streamExpr(h0, v, -1500, 3200, y), u => [-1500 + frac(h0 + u * v) * 3200, y]),
        items: [RECT([len, th], [len / 2, th / 2], th / 2), FILL(col, col === P.white ? .9 : 1)] });
    }
    S.shape({ name: `Stream ${k + 1}`, p: [CX, CY], r: -.42, groups, label: 14 });
  });
  const rise = u => outCubic(prog(0, 1.2, u));
  S.shape({ name: 'Half sun', p: u => [W * .66, H + 60 - 330 * rise(u)], groups: [
    { name: 'Sun', items: [PATH(halfPath(300)), FILL(P.sun)] },
    ...[0, 1, 2, 3, 4].map(k => { const h = 6 + k * 5; return { name: `Stripe ${k + 1}`, items: [RECT([620, h], [0, -40 - k * 46 + h / 2]), FILL(P.azure)] }; })
  ] });
  [[.1, .3, 30, 0], [.18, .36, 20, .15], [.3, .24, 24, .3]].forEach(([x0, y0, sz, o], i) => {
    const a = u => .25 + .4 * Math.abs(Math.sin((u + o) * Math.PI * 3));
    S.shape({ name: `Bird ${i + 1}`, p: u => [W * x0 + u * 380, H * y0 - u * 90], groups: [{ name: 'Wings', items: [
      PATH(ex(birdExpr(sz, o), u => poly([[-sz, -sz * a(u)], [0, 0], [sz, -sz * a(u)]], false))), STROKE(P.white, 5, 1, 'round', 'round')] }] });
  });
  S.shape({ name: 'Sparkles', groups: Array.from({ length: 26 }, (_, i) => {
    const r0 = 3 + 6 * hash(i), d = hash(i * 9) * .8;
    return { name: `Dot ${i + 1}`, p: u => [hash(i * 2.3) * W + u * 300, hash(i * 5.9) * H * .8 - u * 160], s: u => pop(u, d), items: [ELL(2 * r0), FILL(P.white)] };
  }) });
}

function sceneRipple(S) {
  bgSolid(S, P.bg);
  const hit = .42, sy = CY + 60;
  const lineK = u => outExpo(prog(hit, hit + .6, u));
  S.shape({ name: 'Surface', vis: u => lineK(u) > 0, p: [CX, sy], groups: [{ name: 'Line', items: [RECT(u => [1800 * lineK(u), 6], Z2), FILL(P.aqua)] }] });
  S.shape({ name: 'Drop', vis: u => u < hit, p: u => { const p = u / hit; return [CX, lerp(-80, sy - 26, p * p)]; },
    groups: [{ name: 'Drop', items: [ELL(u => { const p = u / hit; return [44 * (1 - .25 * p), 52 * (1 + .45 * p)]; }), FILL(P.deep)] }] });
  for (let k = 0; k < 4; k++) {
    const q = u => prog(hit + k * .16, hit + k * .16 + 1.2, u);
    S.shape({ name: `Ripple ${k + 1}`, vis: u => u >= hit && q(u) > 0 && q(u) < 1, p: [CX, sy], groups: [{ name: 'Ripple', items: [
      ELL(u => { const R = 40 + 820 * outCubic(q(u)); return [2 * R, 2 * R * .24]; }),
      STROKE(k % 2 ? P.turq : P.azure, u => 14 * (1 - q(u)) + 2, u => 1 - q(u))] }] });
  }
  const d = u => prog(hit, hit + .3, u);
  S.shape({ name: 'Rebound', vis: u => u >= hit && d(u) < 1, p: u => [CX, sy - 60 * Math.sin(Math.PI * d(u)) - 10], s: u => 1 - d(u),
    groups: [{ name: 'Drop', items: [ELL(28), FILL(P.deep)] }] });
  for (let i = 0; i < 7; i++) {
    const bt = u => prog(hit + .1 + i * .08, hit + 1.4, u), x = CX + (hash(i * 3.7) - .5) * 360, r0 = 6 + 12 * hash(i);
    S.shape({ name: `Bubble ${i + 1}`, vis: u => u >= hit && bt(u) > 0 && bt(u) < 1, p: u => [x, sy - 20 - 300 * outCubic(bt(u))],
      groups: [{ name: 'Bubble', items: [ELL(u => 2 * r0 * (1 - bt(u) * .4)), STROKE(P.azure, 3)] }] });
  }
}

function sceneSuncatcher(S) {
  bgSolid(S, P.bg);
  const step = u => outExpo(prog(0, .45, u)) + outExpo(prog(1, 1.45, u));
  const rot = u => step(u) * Math.PI / 4, sc = u => pop(u, 0, .3), vis = u => sc(u) > 0;
  const clusters = [[CX, CY, 1.25, 1]];
  for (const sx of [-1, 1]) clusters.push([CX + sx * 640, CY, .7, -1], [CX + sx * 1080, CY, .42, 1]);
  clusters.forEach(([x, y, k, dir], ci) => {
    const nul = S.null({ name: `Cluster ${ci + 1}`, p: [x, y], s: sc, r: u => dir * rot(u) });
    [P.aqua, P.white, P.lav, P.white, P.turq].forEach((col, j) => {
      if (col === P.white) return;                    // white multiplies to nothing
      S.shape({ name: `Cluster ${ci + 1} glass ${j + 1}`, parent: nul, vis, blend: 'multiply', label: 5, r: Math.PI / 4,
        groups: [{ name: 'Diamond', items: [PATH(poly(diamond(250 * k * (1 - j / 5)))), FILL(col)] }] });
    });
    S.shape({ name: `Cluster ${ci + 1} gem`, parent: nul, vis, groups: gemGroups(110 * k, P.turq, P.azure) });
    S.shape({ name: `Cluster ${ci + 1} glint`, parent: nul, vis, r: u => dir * rot(u), s: u => 1 + .3 * Math.sin(u * Math.PI * 4),
      groups: [{ name: 'Star', items: [PATH(poly(starPts(42 * k, .16))), FILL(P.white)] }] });
  });
  S.shape({ name: 'Pluses', groups: Array.from({ length: 12 }, (_, i) => ({
    name: `Plus ${i + 1}`, p: [CX + (i % 6 - 2.5) * 320, CY + (i < 6 ? -380 : 380)], r: u => u * 2 + i,
    s: u => pop(u, .15 + (i % 6) * .08) * (.7 + .3 * Math.sin(u * 8 + i)), items: [...plusItems(14), FILL(P.lav)]
  })) });
}

function sceneChime(S) {
  bgSolid(S, P.bg);
  const ang = u => .34 * Math.cos(Math.PI * u) - .06, len = 540, px = CX + 80, py = -60;
  const ox = u => px + Math.sin(ang(u)) * len, oy = u => py + Math.cos(ang(u)) * len;
  const pend = S.null({ name: 'Pendulum', p: [px, py], r: u => -ang(u) });
  const orb = S.null({ name: 'Orb', parent: pend, p: [0, len], r: ang });   // counter-rotates so the orb stays upright
  S.shape({ name: 'Thread', groups: [{ name: 'Thread', items: [PATH(u => poly([[px, py], [ox(u), oy(u) - 170]], false)), STROKE(P.lav, 5)] }] });
  S.shape({ name: 'Orb aqua', parent: orb, blend: 'multiply', label: 5, p: [-30, 0], groups: [{ name: 'Disc', items: [ELL(344), FILL(P.aqua)] }] });
  S.shape({ name: 'Orb lavender', parent: orb, blend: 'multiply', label: 5, p: [38, 14], groups: [{ name: 'Disc', items: [ELL(280), FILL(P.lav)] }] });
  S.shape({ name: 'Orb highlight', parent: orb, p: [-44, -44], r: Math.PI * .75, groups: [{ name: 'Crescent', items: [PATH(crescentPath(100, .35)), FILL(P.white, .9)] }] });
  S.shape({ name: 'Leaf', parent: pend, p: [0, len + 250], s: 1.5, groups: [{ name: 'Leaf', items: [PATH(leafPath), FILL(P.azure)] }] });
  S.shape({ name: 'Glints', parent: orb, groups: Array.from({ length: 6 }, (_, i) => {
    const a = u => i * TAU / 6 + u, rr = u => 290 + 30 * Math.sin(u * 5 + i);
    return { name: `Glint ${i + 1}`, p: u => [Math.cos(a(u)) * rr(u), Math.sin(a(u)) * rr(u) * .8], r: a,
      s: u => pop(u, .1 + i * .15) * (.6 + .4 * Math.abs(Math.sin(u * 6 + i))), items: [PATH(poly(starPts(24, .16))), FILL(P.turq)] };
  }) });
  [[CY - 300, 9, 0], [CY - 250, 5, .15], [CY + 360, 7, .4], [CY + 405, 4, .55]].forEach(([y0, w, dl], i) => {
    const hd = u => inOutCubic(prog(dl, dl + 1.1, u)), tl = u => inOutCubic(prog(dl + .5, dl + 1.6, u));
    const { path: pth, at } = trimmable(q => [-100 + q * (W + 200), y0 + Math.sin(q * TAU * 1.2) * 26]);
    S.shape({ name: `Wind line ${i + 1}`, vis: u => hd(u) > tl(u), groups: [{ name: 'Line', items: [
      PATH(pth), TRIM(u => at(tl(u)), u => at(hd(u))), STROKE(P.azure, w, 1, 'round')] }] });
  });
}

function sceneDeep(S) {
  const split = Math.round(.55 * H);                  // solids need whole-pixel sizes
  S.solid({ name: 'Water upper', color: P.azure, w: W, h: H, a: [W / 2, H / 2], p: [CX, CY], label: 16, fx: [ramp([0, 0], P.azure, [0, split], P.deep)] });
  S.solid({ name: 'Water lower', color: P.deep, w: W, h: H - split, a: [W / 2, (H - split) / 2], p: [CX, split + (H - split) / 2], label: 16,
    fx: [ramp([0, 0], P.deep, [0, H - split], P.deeper)] });
  for (let k = 0; k < 6; k++) {
    const x0 = hash(k * 4.1) * W, w = 60 + 140 * hash(k * 8.3);
    S.shape({ name: `Light shaft ${k + 1}`, blend: 'screen', o: .22, label: 2, p: u => [60 * Math.sin(u * 2 + k), 0], groups: [{ name: 'Shaft', items: [
      PATH(poly([[x0, -40], [x0 + w, -40], [x0 + w * 1.6 - 380, H + 40], [x0 - 380, H + 40]])), { gfill: { sp: [0, 0], ep: [0, H] } }] }] });
  }
  const zoom = zoomNull(S, u => 1 + .04 * u);
  collageLayers(S, COLLAGE_DEEP, { pan: [60, -520], mul: false, parent: zoom });
  for (let i = 0; i < 14; i++) {
    const t0 = hash(i * 1.7) * .9, q = u => prog(t0, t0 + .9, u), y = H * (.25 + .6 * hash(i * 4.3));
    S.shape({ name: `Fish ${i + 1}`, vis: u => q(u) > 0 && q(u) < 1, p: u => [lerp(-80, W + 80, outCubic(q(u))), y],
      groups: [{ name: 'Fish', items: [PATH(poly([[18, 0], [-12, -9], [-12, 9]])), FILL(i % 3 ? P.aqua : P.lav)] }] });
  }
}

function sceneSail(S) {
  bgSolid(S, P.bg);
  const y0 = CY + 150, amp = 44, kk = TAU / 900;
  const yAt = (x, u) => y0 + Math.sin(x * kk - u * 3.2) * amp;
  const draw = u => outExpo(prog(0, .5, u));
  const swell = (dx, dy) => u => { const pts = [], x0 = CX - 1100 * draw(u), x1 = CX + 1100 * draw(u); for (let x = x0; x <= x1; x += 20) pts.push([x, yAt(x - dx, u) + dy]); return poly(pts, false); };
  S.shape({ name: 'Swell', vis: u => draw(u) > 0, groups: [{ name: 'Wave', items: [PATH(ex(swellExpr(0, 0), swell(0, 0))), STROKE(P.azure, 26, 1, 'round', 'round')] }] });
  S.shape({ name: 'Swell echo', vis: u => draw(u) > 0, groups: [{ name: 'Wave', items: [PATH(ex(swellExpr(120, 70), swell(120, 70))), STROKE(P.aqua, 12, 1, 'round', 'round')] }] });
  const bx = CX - 60, s = u => pop(u, .1, .3);
  S.shape({ name: 'Boat', vis: u => s(u) > 0, p: u => [bx, yAt(bx, u) - 18], r: u => Math.atan((yAt(bx + 30, u) - yAt(bx - 30, u)) / 60), s, groups: [
    { name: 'Hull', items: [RECT([220, 22], [0, 3], 11), FILL(P.deep)] },
    { name: 'Main sail', items: [PATH(poly([[8, -250], [120, -20], [8, -20]])), FILL(P.turq)] },
    { name: 'Jib', items: [PATH(poly([[-8, -210], [-8, -20], [-96, -20]])), FILL(P.lav)] }
  ] });
  S.shape({ name: 'Sun', vis: u => pop(u, .25, .3) > 0, p: [W * .78, H * .24], s: u => pop(u, .25, .3), groups: [{ name: 'Disc', items: [ELL(140), FILL(P.sun)] }] });
  const hd = u => inOutCubic(prog(.3, 1.4, u)), tl = u => inOutCubic(prog(.9, 2, u));
  const { path: pth, at } = trimmable(q => [-100 + q * (W + 200), H * .3 + Math.sin(q * TAU) * 30]);
  S.shape({ name: 'Breeze', vis: u => hd(u) > tl(u), groups: [{ name: 'Line', items: [PATH(pth), TRIM(u => at(tl(u)), u => at(hd(u))), STROKE(P.turq, 4, 1, 'round', 'round')] }] });
}

function sceneWind(S) {
  bgSolid(S, P.turq);
  const groups = [];
  for (let i = 0; i < 62; i++) {
    const y = -900 + hash(i * 3.3) * 1800, th = 14 + 52 * Math.pow(hash(i * 1.9), 2), len = 160 + 640 * hash(i * 7.7);
    const v = (2400 + 2600 * hash(i * 5.1)) / 3600, h0 = hash(i * 9.1), d = hash(i) * .4;
    const col = [P.white, P.white, P.aqua, P.lav, P.azure, P.deep][i % 6];
    groups.push({ name: `Gust ${i + 1}`, p: ex(streamExpr(h0, v, -1700, 3600, y), u => [-1700 + frac(h0 + u * v) * 3600, y]),
      items: [RECT(u => [len * pop(u, d), th], u => [len * pop(u, d) / 2, th / 2], th / 2), FILL(col)] });
  }
  S.shape({ name: 'Gusts', p: [CX, CY], r: -.36, groups, label: 14 });
  S.shape({ name: 'Glints', groups: Array.from({ length: 18 }, (_, i) => {
    const h1 = hash(i * 2.1), h2 = hash(i * 6.7), r0 = 8 + 10 * hash(i), d = hash(i * 4) * .6;
    return { name: `Glint ${i + 1}`, p: ex(wrapXYExpr(h1, .6, W + 200, -100, h2, -.35, H), u => [frac(h1 + u * .6) * (W + 200) - 100, frac(h2 - u * .35) * H]),
      r: u => u * 3 + i, s: u => pop(u, d), items: [...plusItems(r0), FILL(P.white)] };
  }) });
}

function sceneGlint(S) {
  bgSolid(S, P.bg);
  const fOf = u => u - Math.floor(u);
  const step = u => outExpo(prog(0, .5, fOf(u))) + Math.floor(u);
  const sc = u => pop(u, 0, .28) * (1 + .18 * Math.exp(-fOf(u) * 6));
  const vis = u => sc(u) > 0;
  S.shape({ name: 'Halo', vis, p: [CX, CY], groups: [{ name: 'Ring', items: [ELL(u => 380 * sc(u)), STROKE(P.aqua, 6)] }] });
  S.shape({ name: 'Star', vis, p: [CX, CY], s: sc, r: u => step(u) * Math.PI / 4, groups: [{ name: 'Star', items: [PATH(poly(starPts(220, .14))), FILL(P.azure)] }] });
  S.shape({ name: 'Star core', vis, p: [CX, CY], s: sc, r: u => step(u) * Math.PI / 4 + Math.PI / 4, groups: [{ name: 'Star', items: [PATH(poly(starPts(70, .2))), FILL(P.white)] }] });
  S.shape({ name: 'Sparks', vis, groups: Array.from({ length: 8 }, (_, i) => {
    const a = i * TAU / 8;
    return { name: `Spark ${i + 1}`, p: u => { const q = outCubic(fOf(u)); return [CX + Math.cos(a) * (240 + 200 * q), CY + Math.sin(a) * (240 + 200 * q)]; },
      s: u => (1 - outCubic(fOf(u))) * sc(u), items: [ELL(20), FILL(P.turq)] };
  }) });
  const oa = u => -u * Math.PI * 1.4;
  S.shape({ name: 'Moon', vis: u => pop(u, .15) > 0, p: u => [CX + Math.cos(oa(u)) * 390, CY + Math.sin(oa(u)) * 250], r: oa, s: u => pop(u, .15),
    groups: [{ name: 'Crescent', items: [PATH(crescentPath(46, .4)), FILL(P.lav)] }] });
}

function sceneFinale(S) {
  bgSolid(S, P.bg);
  const zoom = zoomNull(S, u => 1 + .03 * u);
  collageLayers(S, COLLAGE_FINALE, { pan: [-220, 140], converge: 1.05, parent: zoom });
  const k = u => outBack(prog(1.55, 2, u), 1.4);
  trioLayers(S, 96, -Math.PI / 2, u => 150 * k(u), u => k(u) > 0);
}

const SCENES = [
  ['SUN', sceneSun], ['BEACH', sceneBeach], ['WAVE', sceneWave], ['SKY', sceneSky], ['RIPPLE', sceneRipple], ['SUNCATCHER', sceneSuncatcher],
  ['CHIME', sceneChime], ['DEEP', sceneDeep], ['SAIL', sceneSail], ['WIND', sceneWind], ['GLINT', sceneGlint], ['FINALE', sceneFinale]
];

/* ------------------------------------------------------------------ *
 *  Sampling and keyframe reduction
 * ------------------------------------------------------------------ */
const uOf = k => k / FPS / BEAT;
const tOf = k => k / FPS;
const rgb4 = h => { const v = parseInt(h.slice(1), 16); return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255, 1].map(x => +x.toFixed(6)); };
const isFn = x => typeof x === 'function';
const isEx = x => x && x.__ex;

// tolerance: how far the linear keys may drift from the real curve; jump: what counts as a cut
const TOL = { pos: .06, scale: .012, rot: .012, op: .12, size: .06, path: .05, trim: .008, width: .03 };
const JUMP = { pos: 60, scale: 5, rot: 30, size: 30, path: 60, op: 40, width: 20, trim: 30 };
const DEC = { pos: 3, scale: 4, rot: 4, op: 3, size: 3, path: 3, trim: 4, width: 3 };

const flat = v => typeof v === 'number' ? [v] : Array.isArray(v) ? v.flat(2) : [...v.v.flat(), ...v.i.flat(), ...v.o.flat()];
const maxDiff = (a, b) => { if (a.length !== b.length) return Infinity; let m = 0; for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i] - b[i])); return m; };
function roundVal(v, d) {
  const r = x => +x.toFixed(d);
  if (typeof v === 'number') return r(v);
  if (Array.isArray(v)) return v.map(x => Array.isArray(x) ? x.map(r) : r(x));
  return { v: v.v.map(p => p.map(r)), i: v.i.map(p => p.map(r)), o: v.o.map(p => p.map(r)), c: v.closed ?? v.c };
}

let keyCount = 0, exprCount = 0;
const exprChecks = [];
function reduceKeys(ks, vals, kind) {
  const F = vals.map(flat), tol = TOL[kind];
  // cut the series where it jumps (a beat hit that resets a value), and hold across the cut
  const segs = []; let s0 = 0;
  for (let i = 0; i < F.length - 1; i++) {
    const d = maxDiff(F[i], F[i + 1]);
    const near = Math.max(i > 0 ? maxDiff(F[i - 1], F[i]) : 0, i < F.length - 2 ? maxDiff(F[i + 1], F[i + 2]) : 0);
    if (d > JUMP[kind] && d > 4 * near) { segs.push([s0, i]); s0 = i + 1; }
  }
  segs.push([s0, F.length - 1]);
  const keep = new Set(), holds = new Set();
  for (const [a, b] of segs) {
    keep.add(a); keep.add(b); if (b !== F.length - 1) holds.add(b);
    const stack = [[a, b]];
    while (stack.length) {
      const [i0, i1] = stack.pop(); if (i1 - i0 < 2) continue;
      let worst = -1, wi = -1;
      for (let i = i0 + 1; i < i1; i++) {
        const t = (ks[i] - ks[i0]) / (ks[i1] - ks[i0]);
        let e = 0; for (let c = 0; c < F[i].length; c++) e = Math.max(e, Math.abs(F[i0][c] + (F[i1][c] - F[i0][c]) * t - F[i][c]));
        if (e > worst) { worst = e; wi = i; }
      }
      if (worst > tol) { keep.add(wi); stack.push([i0, wi], [wi, i1]); }
    }
  }
  const idx = [...keep].sort((x, y) => x - y);
  if (idx.length === 2 && segs.length === 1 && maxDiff(F[idx[0]], F[idx[1]]) <= tol) {
    // constant over the whole range
    let c = true; for (const f of F) if (maxDiff(f, F[0]) > tol) { c = false; break; }
    if (c) return roundVal(vals[0], DEC[kind]);
  }
  keyCount += idx.length;
  const out = { k: idx.map(i => [tOf(ks[i]), roundVal(vals[i], DEC[kind])]) };   // exact frame times
  const h = idx.map((i, j) => holds.has(i) ? j : -1).filter(j => j >= 0);
  if (h.length) out.h = h;
  return out;
}
function anim(val, conv, kind, range) {
  if (val === undefined) return undefined;
  if (isEx(val)) {
    exprCount++;
    exprChecks.push({ code: val.code, fn: val.fn, conv, kind, range });
    return { x: val.code, v: roundVal(conv(val.fn(uOf(range[0]))), DEC[kind]) };
  }
  if (!isFn(val)) return roundVal(conv(val), DEC[kind]);
  const ks = [], vals = [];
  for (let k = range[0]; k <= range[1]; k++) {
    const v = conv(val(uOf(k)));
    if (flat(v).some(x => !Number.isFinite(x))) continue;
    ks.push(k); vals.push(v);
  }
  return reduceKeys(ks, vals, kind);
}
const cPos = v => v, cSize = v => typeof v === 'number' ? [v, v] : v;
const cScale = s => typeof s === 'number' ? [s * 100, s * 100] : [s[0] * 100, s[1] * 100];
const cRot = r => r * 180 / Math.PI, cOp = o => o * 100, cNum = v => v, cTrim = v => v * 100;
const cPath = p => p;

function emitTransform(spec, range, isLayer) {
  const tr = {};
  const p = spec.p ?? (isLayer ? Z2 : undefined);
  if (isLayer && isFn(p)) {                            // separate X/Y so each gets its own keys (and no spatial curves)
    const x = anim(u => p(u)[0], cNum, 'pos', range), y = anim(u => p(u)[1], cNum, 'pos', range);
    tr.p = { sep: true, x, y };
  } else if (p !== undefined) tr.p = anim(p, cPos, 'pos', range);
  const a = spec.a ?? (isLayer ? Z2 : undefined);
  if (a !== undefined) tr.a = anim(a, cPos, 'pos', range);
  const s = spec.s ?? (isLayer ? 1 : undefined);
  if (s !== undefined) tr.s = anim(s, cScale, 'scale', range);
  const r = spec.r ?? (isLayer ? 0 : undefined);
  if (r !== undefined) tr.r = anim(r, cRot, 'rot', range);
  const o = spec.o ?? (isLayer ? 1 : undefined);
  if (o !== undefined) tr.o = anim(o, cOp, 'op', range);
  if (!isLayer) {                                      // drop group defaults
    if (tr.a && !tr.a.k && !tr.a.x && tr.a[0] === 0 && tr.a[1] === 0) delete tr.a;
  }
  return tr;
}
const CAP = { butt: 1, round: 2, square: 3 }, JOIN = { miter: 1, round: 2, bevel: 3 };
function emitItem(it, range) {
  if (it.ell) return { t: 'ell', size: anim(it.ell.d, cSize, 'size', range), ...(it.ell.c ? { pos: anim(it.ell.c, cPos, 'pos', range) } : {}) };
  if (it.rect) return { t: 'rect', size: anim(it.rect.size, cSize, 'size', range), pos: anim(it.rect.c, cPos, 'pos', range), round: anim(it.rect.round, cNum, 'size', range) };
  if (it.path) return { t: 'path', path: anim(it.path, cPath, 'path', range) };
  if (it.trim) return { t: 'trim', s: anim(it.trim.s, cTrim, 'trim', range), e: anim(it.trim.e, cTrim, 'trim', range) };
  if (it.fill) return { t: 'fill', c: rgb4(it.fill.c), o: anim(it.fill.o, cOp, 'op', range), ...(it.fill.rule === 'eo' ? { rule: 2 } : {}) };
  if (it.stroke) return { t: 'stroke', c: rgb4(it.stroke.c), w: anim(it.stroke.w, cNum, 'width', range), o: anim(it.stroke.o, cOp, 'op', range), cap: CAP[it.stroke.cap], join: JOIN[it.stroke.join] };
  if (it.gfill) return { t: 'gfill', sp: it.gfill.sp, ep: it.gfill.ep };
  throw new Error('unknown item ' + JSON.stringify(Object.keys(it)));
}
function emitGroup(g, range) {
  const out = { n: g.name, items: g.items.filter(x => !(x.fill || x.stroke || x.gfill || x.trim)).map(x => emitItem(x, range)) };
  // operators, then paint below the paths they act on
  for (const x of g.items) if (x.trim) out.items.push(emitItem(x, range));
  for (const x of g.items) if (x.fill || x.stroke || x.gfill) out.items.push(emitItem(x, range));
  const tr = emitTransform(g, range, false);
  if (Object.keys(tr).length) out.tr = tr;
  return out;
}

function emitScene(name, build, index) {
  const S = new Scene(name);
  build(S);
  const ids = new Set();
  const layers = S.layers.map(l => {
    if (l.parent && !ids.has(l.parent.id)) throw new Error(`${name}: parent of ${l.name} must come first`);
    ids.add(l.id);
    // visible frames → in/out points; sample one frame either side for motion blur
    let f0 = 0, f1 = SF - 1;
    if (l.vis) {
      const on = []; for (let k = 0; k < SF; k++) if (l.vis(uOf(k))) on.push(k);
      if (!on.length) throw new Error(`${name}: ${l.name} is never visible`);
      f0 = on[0]; f1 = on[on.length - 1];
      if (on.length !== f1 - f0 + 1) throw new Error(`${name}: ${l.name} visibility is not contiguous`);
    }
    const range = [Math.max(0, f0 - 1), Math.min(SF, f1 + 1)];
    const out = { id: l.id, n: l.name, t: l.kind };
    if (l.parent) out.parent = l.parent.id;
    if (l.kind === 'solid') {
      if (!Number.isInteger(l.w) || !Number.isInteger(l.h)) throw new Error(`${name}: solid ${l.name} needs whole-pixel size`);
      out.color = rgb4(l.color).slice(0, 3); out.w = l.w; out.h = l.h;
    }
    if (l.fx) out.fx = l.fx;
    if (l.groups) out.groups = [...l.groups].reverse().map(g => emitGroup(g, range));
    out.tr = emitTransform(l, range, true);
    if (l.blend && l.blend !== 'normal') out.blend = l.blend;
    if (l.label !== undefined) out.label = l.label;
    else if (l.kind === 'null') out.label = 1;
    else if (l.kind === 'shape') out.label = l.blend === 'multiply' ? 5 : l.blend === 'screen' ? 2 : 8;
    if (f0 > 0) out.inp = tOf(f0);
    if (f1 < SF - 1) out.outp = tOf(f1 + 1);
    return out;
  });
  // AE adds each new layer on top, so layers are created bottom → top as listed here
  return { id: 'scene' + index, name: `${pad2(index + 1)} ${name}`, w: W, h: H, dur: SCENE, fps: FPS, bg: rgb4(P.bg).slice(0, 3), layers };
}

/* ------------------------------------------------------------------ *
 *  Expression self-check: evaluate every expression the way AE would
 *  (last line is the value) and compare it with its JS twin.
 * ------------------------------------------------------------------ */
export function createPath(points, inT = [], outT = [], closed = true) {
  return { v: points, i: inT.length ? inT : points.map(() => [0, 0]), o: outT.length ? outT : points.map(() => [0, 0]), c: closed };
}
export function compileExpr(code) {
  const lines = code.trim().split('\n'), last = lines.pop().replace(/;\s*$/, '');
  return new Function('time', 'thisLayer', 'createPath', 'value', lines.join('\n') + '\nreturn (' + last + ');');
}
function checkExpressions() {
  let worst = 0;
  for (const c of exprChecks) {
    const f = compileExpr(c.code);
    for (let k = c.range[0]; k <= c.range[1]; k++) {
      const got = f(tOf(k), { startTime: 0 }, createPath), want = c.conv(c.fn(uOf(k)));
      const d = maxDiff(flat(got), flat(want));
      worst = Math.max(worst, d);
      if (!(d < 1e-6)) throw new Error(`expression mismatch (${d}) at frame ${k}:\n${c.code}`);
    }
  }
  return worst;
}

/* ------------------------------------------------------------------ *
 *  Main
 * ------------------------------------------------------------------ */
export function buildDoc() {
  const scenes = SCENES.map(([name, fn], i) => emitScene(name, fn, i));
  const main = {
    id: 'main', name: 'Seaglass', w: W, h: H, dur: L, fps: FPS, bg: rgb4(P.bg).slice(0, 3), main: true,
    markers: SCENES.map(([name], i) => [i * SF / FPS, `${pad2(i + 1)} ${name}`]),
    layers: [
      ...scenes.map((s, i) => ({ id: 'L' + s.id, n: s.name, t: 'comp', src: s.id, st: i * SF / FPS, label: 9 })).reverse(),
      { id: 'audio', n: 'Soundtrack', t: 'file', file: 'audio/seaglass.wav', label: 12, beats: 24 },
      { id: 'ref', n: 'Reference render (guide)', t: 'file', file: '../seaglass.mp4', guide: true, label: 0 }
    ]
  };
  return {
    name: 'Seaglass', bpm: BPM, comps: [...scenes, main],
    stems: ['audio/stems/seaglass-drums.wav', 'audio/stems/seaglass-bass.wav', 'audio/stems/seaglass-music.wav', 'audio/stems/seaglass-fx.wav']
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const doc = buildDoc();
  const worst = checkExpressions();
  const runtime = fs.readFileSync(path.join(HERE, 'runtime.jsx'), 'utf8');
  const layerCount = doc.comps.reduce((a, c) => a + c.layers.length, 0);
  const header = [
    '// Seaglass: After Effects project builder',
    '// Generated by ae/build.mjs from the scenes in index.html. Do not edit by hand; rebuild instead.',
    '//',
    '// In After Effects: File > Scripts > Run Script File... and choose this file.',
    '// It builds a "Seaglass" folder with the 15 s main comp (1920x1080, 60 fps), one precomp per',
    '// scene, the soundtrack from ae/audio/ and, if present, ../seaglass.mp4 as a guide layer.',
    `// ${doc.comps.length} comps, ${layerCount} layers, ${keyCount} keyframes, ${exprCount} expressions.`,
    ''
  ].join('\n');
  const js = header + runtime.replace('/*__DOC__*/null', JSON.stringify(doc));
  if (/[^\x00-\x7f]/.test(js)) throw new Error('jsx must stay ASCII');
  const out = path.join(HERE, 'Seaglass.jsx');
  fs.writeFileSync(out, js);
  console.log(`wrote ${path.relative(process.cwd(), out)}: ${(js.length / 1024).toFixed(0)} KB, ${doc.comps.length} comps, ${layerCount} layers, ${keyCount} keys, ${exprCount} expressions (max expression error ${worst.toExponential(1)})`);
}
