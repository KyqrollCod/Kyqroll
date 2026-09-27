// Renders a project recorded by mock-ae.mjs with After Effects' rules (layer order, parenting,
// anchor/position/scale/rotation, shape group stacking, blend modes, hold keys, expressions).
// Motion blur is left out on both sides of the comparison.
(() => {
  const exprCache = new Map();
  function compileExpr(code) {
    if (!exprCache.has(code)) {
      const lines = code.trim().split('\n'), last = lines.pop().replace(/;\s*$/, '');
      exprCache.set(code, new Function('time', 'thisLayer', 'createPath', 'value', lines.join('\n') + '\nreturn (' + last + ');'));
    }
    return exprCache.get(code);
  }
  const createPath = (points, inT = [], outT = [], closed = true) =>
    ({ v: points, i: inT.length ? inT : points.map(() => [0, 0]), o: outT.length ? outT : points.map(() => [0, 0]), c: closed });

  function lerpV(a, b, f) {
    if (typeof a === 'number') return a + (b - a) * f;
    if (Array.isArray(a)) return a.map((x, i) => lerpV(x, b[i], f));
    return { v: lerpV(a.v, b.v, f), i: lerpV(a.i, b.i, f), o: lerpV(a.o, b.o, f), c: a.c };
  }
  function val(p, t, layer) {
    if (!p) return undefined;
    let base = p.v;
    if (p.keys && p.keys.length) {
      const ks = p.keys;
      if (t <= ks[0].t + 1e-9) base = ks[0].v;
      else if (t >= ks[ks.length - 1].t - 1e-9) base = ks[ks.length - 1].v;
      else {
        let i = 0; while (i < ks.length - 2 && ks[i + 1].t <= t + 1e-9) i++;
        if (ks[i].o === 'hold') base = ks[i].v;
        else {
          if (ks[i].o !== 'linear') throw new Error('only linear and hold keys are expected');
          base = lerpV(ks[i].v, ks[i + 1].v, (t - ks[i].t) / (ks[i + 1].t - ks[i].t));
        }
      }
    }
    if (p.x) return compileExpr(p.x)(t, { startTime: layer.start }, createPath, base);
    return base;
  }

  const rgba = (c, a = 1) => `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${a * (c[3] ?? 1)})`;
  const K = .5522847498;
  function shapePath(s, P = new Path2D()) {
    const n = s.v.length; if (!n) return P;
    P.moveTo(s.v[0][0], s.v[0][1]);
    const seg = (a, b) => P.bezierCurveTo(s.v[a][0] + s.o[a][0], s.v[a][1] + s.o[a][1], s.v[b][0] + s.i[b][0], s.v[b][1] + s.i[b][1], s.v[b][0], s.v[b][1]);
    for (let k = 0; k < n - 1; k++) seg(k, k + 1);
    if (s.c) { seg(n - 1, 0); P.closePath(); }
    return P;
  }
  function ellipseShape(size, pos) {        // AE draws ellipses from the top, clockwise, as four cubic segments
    const rx = size[0] / 2, ry = size[1] / 2, [x, y] = pos;
    return { v: [[x, y - ry], [x + rx, y], [x, y + ry], [x - rx, y]],
      i: [[-rx * K, 0], [0, -ry * K], [rx * K, 0], [0, ry * K]], o: [[rx * K, 0], [0, ry * K], [-rx * K, 0], [0, -ry * K]], c: true };
  }
  function rectShape(size, pos, round) {
    const [w, h] = size, [x, y] = pos, r = Math.max(0, Math.min(round, w / 2, h / 2));
    const l = x - w / 2, t = y - h / 2, R = x + w / 2, B = y + h / 2;
    if (r <= 0) return { v: [[R, t], [R, B], [l, B], [l, t]], i: [[0, 0], [0, 0], [0, 0], [0, 0]], o: [[0, 0], [0, 0], [0, 0], [0, 0]], c: true };
    const k = r * K;
    return {
      v: [[R, t + r], [R, B - r], [R - r, B], [l + r, B], [l, B - r], [l, t + r], [l + r, t], [R - r, t]],
      i: [[0, -k], [0, 0], [k, 0], [0, 0], [0, k], [0, 0], [-k, 0], [0, 0]],
      o: [[0, 0], [0, k], [0, 0], [-k, 0], [0, 0], [0, -k], [0, 0], [k, 0]], c: true
    };
  }
  function flatten(s) {                      // polyline(s) for Trim Paths
    const pts = [], n = s.v.length;
    const seg = (a, b) => {
      const p0 = s.v[a], p1 = [p0[0] + s.o[a][0], p0[1] + s.o[a][1]], p3 = s.v[b], p2 = [p3[0] + s.i[b][0], p3[1] + s.i[b][1]];
      const straight = s.o[a][0] === 0 && s.o[a][1] === 0 && s.i[b][0] === 0 && s.i[b][1] === 0, N = straight ? 1 : 24;
      for (let j = 1; j <= N; j++) {
        const t = j / N, u = 1 - t;
        pts.push([u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0], u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]]);
      }
    };
    pts.push(s.v[0]);
    for (let k = 0; k < n - 1; k++) seg(k, k + 1);
    if (s.c) seg(n - 1, 0);
    return pts;
  }
  function trimmed(pts, a, b) {
    const acc = [0]; for (let k = 1; k < pts.length; k++) acc.push(acc[k - 1] + Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]));
    const tot = acc[acc.length - 1], s0 = Math.min(a, b) * tot, s1 = Math.max(a, b) * tot;
    const at = s => { let k = 1; while (k < acc.length - 1 && acc[k] < s) k++; const f = (s - acc[k - 1]) / ((acc[k] - acc[k - 1]) || 1); return [pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * f, pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * f]; };
    const P = new Path2D(); if (s1 - s0 <= 0) return P;
    const p0 = at(s0); P.moveTo(p0[0], p0[1]);
    for (let k = 1; k < acc.length; k++) if (acc[k] > s0 && acc[k] < s1) P.lineTo(pts[k][0], pts[k][1]);
    const p1 = at(s1); P.lineTo(p1[0], p1[1]);
    return P;
  }

  function matrixOf(tr, t, layer, isGroup) {
    const g = k => val(tr[k], t, layer);
    let p, a, s, r;
    if (isGroup) { a = g('ADBE Vector Anchor'); p = g('ADBE Vector Position'); s = g('ADBE Vector Scale'); r = g('ADBE Vector Rotation'); }
    else {
      a = g('ADBE Anchor Point');
      p = layer.sep ? [g('ADBE Position_0'), g('ADBE Position_1')] : g('ADBE Position');
      s = g('ADBE Scale'); r = g('ADBE Rotate Z');
    }
    return new DOMMatrix().translate(p[0], p[1]).rotate(r).scale(s[0] / 100, s[1] / 100).translate(-a[0], -a[1]);
  }

  function drawVectors(ctx, items, t, layer) {
    // items are top-first; each paint renders the paths listed above it, after the operators above it
    for (let idx = items.length - 1; idx >= 0; idx--) {
      const it = items[idx];
      if (it.mn === 'ADBE Vector Group') {
        const tr = it.transform, op = val(tr['ADBE Vector Group Opacity'], t, layer) / 100;
        ctx.save(); ctx.setTransform(ctx.getTransform().multiply(matrixOf(tr, t, layer, true))); ctx.globalAlpha *= op;
        drawVectors(ctx, it.contents, t, layer); ctx.restore();
        continue;
      }
      if (!/Graphic/.test(it.mn)) continue;
      const shapes = [], trims = [];
      for (let j = 0; j < idx; j++) {
        const q = items[j], P = q.props;
        if (q.mn === 'ADBE Vector Shape - Ellipse') shapes.push(ellipseShape(val(P['ADBE Vector Ellipse Size'], t, layer), val(P['ADBE Vector Ellipse Position'], t, layer)));
        else if (q.mn === 'ADBE Vector Shape - Rect') shapes.push(rectShape(val(P['ADBE Vector Rect Size'], t, layer), val(P['ADBE Vector Rect Position'], t, layer), val(P['ADBE Vector Rect Roundness'], t, layer)));
        else if (q.mn === 'ADBE Vector Shape - Group') shapes.push(val(P['ADBE Vector Shape'], t, layer));
        else if (q.mn === 'ADBE Vector Filter - Trim') trims.push([val(P['ADBE Vector Trim Start'], t, layer) / 100, val(P['ADBE Vector Trim End'], t, layer) / 100]);
        else if (q.mn === 'ADBE Vector Group') throw new Error('nested groups above a paint are not expected');
      }
      let path = new Path2D();
      if (trims.length) { if (trims.length > 1 || shapes.length > 1) throw new Error('one trimmed path per group expected'); path = trimmed(flatten(shapes[0]), trims[0][0], trims[0][1]); }
      else for (const s of shapes) shapePath(s, path);
      const P = it.props;
      if (it.mn === 'ADBE Vector Graphic - Fill') {
        ctx.fillStyle = rgba(val(P['ADBE Vector Fill Color'], t, layer), val(P['ADBE Vector Fill Opacity'], t, layer) / 100);
        ctx.fill(path, val(P['ADBE Vector Fill Rule'], t, layer) === 2 ? 'evenodd' : 'nonzero');
      } else if (it.mn === 'ADBE Vector Graphic - Stroke') {
        ctx.strokeStyle = rgba(val(P['ADBE Vector Stroke Color'], t, layer), val(P['ADBE Vector Stroke Opacity'], t, layer) / 100);
        ctx.lineWidth = val(P['ADBE Vector Stroke Width'], t, layer);
        ctx.lineCap = ['butt', 'round', 'square'][val(P['ADBE Vector Stroke Line Cap'], t, layer) - 1];
        ctx.lineJoin = ['miter', 'round', 'bevel'][val(P['ADBE Vector Stroke Line Join'], t, layer) - 1];
        ctx.miterLimit = val(P['ADBE Vector Stroke Miter Limit'], t, layer);
        ctx.stroke(path);
      } else if (it.mn === 'ADBE Vector Graphic - G-Fill') {
        const a = val(P['ADBE Vector Grad Start Pt'], t, layer), b = val(P['ADBE Vector Grad End Pt'], t, layer);
        if (val(P['ADBE Vector Grad Type'], t, layer) !== 1) throw new Error('linear gradients only');
        const g = ctx.createLinearGradient(a[0], a[1], b[0], b[1]); g.addColorStop(0, '#fff'); g.addColorStop(1, '#000');   // AE's default gradient
        ctx.globalAlpha *= val(P['ADBE Vector Fill Opacity'], t, layer) / 100; ctx.fillStyle = g; ctx.fill(path);
      }
    }
  }

  const pool = [];
  function canvas(w, h) { const c = pool.pop() || document.createElement('canvas'); c.width = w; c.height = h; return c; }

  function renderComp(proj, comp, t) {
    const out = canvas(comp.w, comp.h), ctx = out.getContext('2d');
    const byId = new Map(comp.layers.map(L => [L.id, L]));
    const world = L => { let m = matrixOf(L.transform, t, L, false); for (let p = L.parent; p != null; p = byId.get(p).parent) m = matrixOf(byId.get(p).transform, t, byId.get(p), false).multiply(m); return m; };
    for (let li = comp.layers.length - 1; li >= 0; li--) {
      const L = comp.layers[li];
      if (!L.enabled || L.guide || L.type === 'null' || L.type === 'footage') continue;
      if (t < L.inPoint - 1e-9 || t >= L.outPoint - 1e-9) continue;
      const op = val(L.transform['ADBE Opacity'], t, L) / 100; if (op <= 0) continue;
      const lay = canvas(comp.w, comp.h), lc = lay.getContext('2d');
      lc.setTransform(world(L));
      if (L.type === 'solid') {
        const ramp = L.effects.find(e => e.mn === 'ADBE Ramp');
        if (ramp) {
          const g = k => val(ramp.props[k], t, L), a = g('ADBE Ramp-0001'), b = g('ADBE Ramp-0003');
          if (g('ADBE Ramp-0005') !== 1) throw new Error('linear ramps only');
          const gr = lc.createLinearGradient(a[0], a[1], b[0], b[1]); gr.addColorStop(0, rgba(g('ADBE Ramp-0002'))); gr.addColorStop(1, rgba(g('ADBE Ramp-0004')));
          lc.fillStyle = gr;
        } else lc.fillStyle = rgba(L.solid.color);
        lc.fillRect(0, 0, L.solid.w, L.solid.h);
      } else if (L.type === 'shape') drawVectors(lc, L.contents, t, L);
      else if (L.type === 'comp') { const sub = renderComp(proj, proj.comps.find(c => c.id === L.source), t - L.start); lc.drawImage(sub, 0, 0); pool.push(sub); }
      ctx.globalAlpha = op; ctx.globalCompositeOperation = { normal: 'source-over', multiply: 'multiply', screen: 'screen' }[L.blend];
      ctx.drawImage(lay, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      pool.push(lay);
    }
    return out;
  }

  let PROJ = null, MAIN = null;
  window.__load = json => { PROJ = JSON.parse(json); MAIN = PROJ.comps.find(c => c.dur === 15); return PROJ.comps.length; };
  window.__compare = async (fi, origURL, wantDiff) => {
    const t = fi / 60;
    const ae = renderComp(PROJ, MAIN, t);
    const img = new Image(); img.src = origURL; await img.decode();
    const oc = canvas(1920, 1080), octx = oc.getContext('2d'); octx.drawImage(img, 0, 0);
    const A = ae.getContext('2d').getImageData(0, 0, 1920, 1080).data, B = octx.getImageData(0, 0, 1920, 1080).data;
    let sum = 0, over = 0, max = 0;
    const D = wantDiff ? new ImageData(1920, 1080) : null;
    for (let i = 0; i < A.length; i += 4) {
      const d = Math.max(Math.abs(A[i] - B[i]), Math.abs(A[i + 1] - B[i + 1]), Math.abs(A[i + 2] - B[i + 2]));
      sum += (Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1]) + Math.abs(A[i + 2] - B[i + 2])) / 3;
      if (d > 32) over++;
      if (d > max) max = d;
      if (D) { const v = Math.min(255, d * 4); D.data[i] = v; D.data[i + 1] = v; D.data[i + 2] = v; D.data[i + 3] = 255; }
    }
    const res = { fi, mean: sum / (A.length / 4), over: over / (A.length / 4), max };
    if (wantDiff) {
      const dc = canvas(1920, 1080); dc.getContext('2d').putImageData(D, 0, 0);
      res.ae = ae.toDataURL('image/png'); res.diff = dc.toDataURL('image/png'); pool.push(dc);
    }
    pool.push(ae, oc);
    return res;
  };
})();
