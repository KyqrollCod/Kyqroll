// A strict stand-in for the parts of the After Effects scripting DOM that Seaglass.jsx uses.
// It rejects unknown match names, wrong value shapes and out-of-range enums, and records the
// resulting project so verify.mjs can render it and compare it with the canvas original.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const prop = (dims, def, extra = {}) => ({ kind: 'prop', dims, def, ...extra });
const group = (children, extra = {}) => ({ kind: 'group', children, ...extra });
const indexed = accepts => ({ kind: 'indexed', accepts });
const SHAPES = ['ADBE Vector Shape - Ellipse', 'ADBE Vector Shape - Rect', 'ADBE Vector Shape - Group', 'ADBE Vector Filter - Trim',
  'ADBE Vector Graphic - Fill', 'ADBE Vector Graphic - Stroke', 'ADBE Vector Graphic - G-Fill', 'ADBE Vector Group'];

const SCHEMA = {
  'ADBE Transform Group': group(['ADBE Anchor Point', 'ADBE Position', 'ADBE Position_0', 'ADBE Position_1', 'ADBE Scale', 'ADBE Rotate Z', 'ADBE Opacity']),
  'ADBE Anchor Point': prop([2, 3], null, { spatial: true }),
  'ADBE Position': prop([2, 3], null, { spatial: true, separable: true }),
  'ADBE Position_0': prop([1], null), 'ADBE Position_1': prop([1], null),
  'ADBE Scale': prop([2, 3], [100, 100]), 'ADBE Rotate Z': prop([1], 0), 'ADBE Opacity': prop([1], 100, { range: [0, 100] }),
  'ADBE Root Vectors Group': indexed(['ADBE Vector Group']),
  'ADBE Vector Group': group(['ADBE Vectors Group', 'ADBE Vector Transform Group']),
  'ADBE Vectors Group': indexed(SHAPES),
  'ADBE Vector Transform Group': group(['ADBE Vector Anchor', 'ADBE Vector Position', 'ADBE Vector Scale', 'ADBE Vector Skew', 'ADBE Vector Skew Axis', 'ADBE Vector Rotation', 'ADBE Vector Group Opacity']),
  'ADBE Vector Anchor': prop([2], [0, 0], { spatial: true }), 'ADBE Vector Position': prop([2], [0, 0], { spatial: true }),
  'ADBE Vector Scale': prop([2], [100, 100]), 'ADBE Vector Skew': prop([1], 0), 'ADBE Vector Skew Axis': prop([1], 0),
  'ADBE Vector Rotation': prop([1], 0), 'ADBE Vector Group Opacity': prop([1], 100, { range: [0, 100] }),
  'ADBE Vector Shape - Ellipse': group(['ADBE Vector Shape Direction', 'ADBE Vector Ellipse Size', 'ADBE Vector Ellipse Position']),
  'ADBE Vector Ellipse Size': prop([2], [100, 100]), 'ADBE Vector Ellipse Position': prop([2], [0, 0], { spatial: true }),
  'ADBE Vector Shape - Rect': group(['ADBE Vector Shape Direction', 'ADBE Vector Rect Size', 'ADBE Vector Rect Position', 'ADBE Vector Rect Roundness']),
  'ADBE Vector Rect Size': prop([2], [100, 100]), 'ADBE Vector Rect Position': prop([2], [0, 0], { spatial: true }), 'ADBE Vector Rect Roundness': prop([1], 0),
  'ADBE Vector Shape - Group': group(['ADBE Vector Shape Direction', 'ADBE Vector Shape']),
  'ADBE Vector Shape': prop(['shape'], null),
  'ADBE Vector Shape Direction': prop([1], 1, { enum: [1, 2, 3] }),
  'ADBE Vector Filter - Trim': group(['ADBE Vector Trim Start', 'ADBE Vector Trim End', 'ADBE Vector Trim Offset', 'ADBE Vector Trim Type']),
  'ADBE Vector Trim Start': prop([1], 0, { range: [0, 100] }), 'ADBE Vector Trim End': prop([1], 100, { range: [0, 100] }),
  'ADBE Vector Trim Offset': prop([1], 0), 'ADBE Vector Trim Type': prop([1], 1, { enum: [1, 2] }),
  'ADBE Vector Graphic - Fill': group(['ADBE Vector Blend Mode', 'ADBE Vector Composite Order', 'ADBE Vector Fill Rule', 'ADBE Vector Fill Color', 'ADBE Vector Fill Opacity']),
  'ADBE Vector Graphic - Stroke': group(['ADBE Vector Blend Mode', 'ADBE Vector Composite Order', 'ADBE Vector Stroke Color', 'ADBE Vector Stroke Opacity', 'ADBE Vector Stroke Width', 'ADBE Vector Stroke Line Cap', 'ADBE Vector Stroke Line Join', 'ADBE Vector Stroke Miter Limit']),
  'ADBE Vector Graphic - G-Fill': group(['ADBE Vector Blend Mode', 'ADBE Vector Composite Order', 'ADBE Vector Fill Rule', 'ADBE Vector Grad Type', 'ADBE Vector Grad Start Pt', 'ADBE Vector Grad End Pt', 'ADBE Vector Grad HiLite Length', 'ADBE Vector Grad HiLite Angle', 'ADBE Vector Grad Colors', 'ADBE Vector Fill Opacity']),
  'ADBE Vector Blend Mode': prop([1], 1), 'ADBE Vector Composite Order': prop([1], 1, { enum: [1, 2] }),
  'ADBE Vector Fill Rule': prop([1], 1, { enum: [1, 2] }), 'ADBE Vector Fill Color': prop([4], [1, 0, 0, 1], { color: true }),
  'ADBE Vector Fill Opacity': prop([1], 100, { range: [0, 100] }),
  'ADBE Vector Stroke Color': prop([4], [1, 1, 1, 1], { color: true }), 'ADBE Vector Stroke Opacity': prop([1], 100, { range: [0, 100] }),
  'ADBE Vector Stroke Width': prop([1], 2, { range: [0, 1e6] }), 'ADBE Vector Stroke Line Cap': prop([1], 1, { enum: [1, 2, 3] }),
  'ADBE Vector Stroke Line Join': prop([1], 1, { enum: [1, 2, 3] }), 'ADBE Vector Stroke Miter Limit': prop([1], 4),
  'ADBE Vector Grad Type': prop([1], 1, { enum: [1, 2] }), 'ADBE Vector Grad Start Pt': prop([2], [0, 0], { spatial: true }),
  'ADBE Vector Grad End Pt': prop([2], [100, 0], { spatial: true }), 'ADBE Vector Grad HiLite Length': prop([1], 0),
  'ADBE Vector Grad HiLite Angle': prop([1], 0), 'ADBE Vector Grad Colors': prop(['nosc'], null),
  'ADBE Effect Parade': indexed(['ADBE Ramp']),
  'ADBE Ramp': group(['ADBE Ramp-0001', 'ADBE Ramp-0002', 'ADBE Ramp-0003', 'ADBE Ramp-0004', 'ADBE Ramp-0005', 'ADBE Ramp-0006', 'ADBE Ramp-0007']),
  'ADBE Ramp-0001': prop([2], [0, 0], { spatial: true }), 'ADBE Ramp-0002': prop([4], [0, 0, 0, 1], { color: true }),
  'ADBE Ramp-0003': prop([2], [0, 100], { spatial: true }), 'ADBE Ramp-0004': prop([4], [1, 1, 1, 1], { color: true }),
  'ADBE Ramp-0005': prop([1], 1, { enum: [1, 2] }), 'ADBE Ramp-0006': prop([1], 0), 'ADBE Ramp-0007': prop([1], 0),
  'ADBE Marker': prop(['marker'], null)
};
const DISPLAY = { 'ADBE Vector Group': 'Group', 'ADBE Vector Shape - Ellipse': 'Ellipse Path', 'ADBE Vector Shape - Rect': 'Rectangle Path', 'ADBE Vector Shape - Group': 'Path',
  'ADBE Vector Filter - Trim': 'Trim Paths', 'ADBE Vector Graphic - Fill': 'Fill', 'ADBE Vector Graphic - Stroke': 'Stroke', 'ADBE Vector Graphic - G-Fill': 'Gradient Fill', 'ADBE Ramp': 'Gradient Ramp' };

export function runJsx(jsxPath, { allowAlerts = false } = {}) {
  const log = [];
  const fail = msg => { throw new Error(msg); };
  class Shape { constructor() { this.vertices = []; this.inTangents = []; this.outTangents = []; this.closed = true; } }
  class MarkerValue { constructor(comment) { this.comment = comment; } }
  const KeyframeInterpolationType = { LINEAR: 'linear', BEZIER: 'bezier', HOLD: 'hold' };
  const BlendingMode = { NORMAL: 'normal', MULTIPLY: 'multiply', SCREEN: 'screen', ADD: 'add' };
  const TrackMatteType = { NO_TRACK_MATTE: 'none', ALPHA: 'alpha', ALPHA_INVERTED: 'alpha-inv', LUMA: 'luma', LUMA_INVERTED: 'luma-inv' };

  function checkValue(mn, spec, v) {
    const d = spec.dims[0];
    if (d === 'nosc') fail(`${mn} cannot be set by scripting`);
    if (d === 'marker') { if (!(v instanceof MarkerValue)) fail(`${mn} needs a MarkerValue`); return v; }
    if (d === 'shape') {
      if (!(v instanceof Shape)) fail(`${mn} needs a Shape`);
      const n = v.vertices.length;
      if (v.inTangents.length !== n || v.outTangents.length !== n) fail(`${mn}: tangent count mismatch`);
      for (const a of [...v.vertices, ...v.inTangents, ...v.outTangents]) if (a.length !== 2 || !a.every(Number.isFinite)) fail(`${mn}: bad point`);
      return { v: v.vertices.map(p => [...p]), i: v.inTangents.map(p => [...p]), o: v.outTangents.map(p => [...p]), c: !!v.closed };
    }
    if (spec.dims.includes(1) && typeof v === 'number') {
      if (!Number.isFinite(v)) fail(`${mn}: not finite`);
      if (spec.enum && !spec.enum.includes(v)) fail(`${mn}: ${v} not in ${spec.enum}`);
      if (spec.range && (v < spec.range[0] - 1e-9 || v > spec.range[1] + 1e-9)) fail(`${mn}: ${v} out of range`);
      return v;
    }
    if (!Array.isArray(v) || !spec.dims.includes(v.length) || !v.every(Number.isFinite)) fail(`${mn}: bad value ${JSON.stringify(v)}`);
    if (spec.color && v.some(x => x < 0 || x > 1)) fail(`${mn}: colour out of range`);
    return [...v];
  }

  class Property {
    constructor(mn, parent) {
      this.matchName = mn; this.spec = SCHEMA[mn]; this.parentProperty = parent; this.name = mn;
      this.value = this.spec.def; this.keys = []; this.expression = ''; this._sep = false;
    }
    get isSpatial() { return !!this.spec.spatial; }
    get numKeys() { return this.keys.length; }
    set dimensionsSeparated(b) { if (!this.spec.separable) fail(`${this.matchName} cannot be separated`); this._sep = !!b; }
    get dimensionsSeparated() { return this._sep; }
    setValue(v) { if (this.keys.length) fail(`${this.matchName}: setValue on a keyed property`); this.value = checkValue(this.matchName, this.spec, v); }
    setValueAtTime(t, v) { this.setValuesAtTimes([t], [v]); }
    setValuesAtTimes(ts, vs) {
      if (ts.length !== vs.length) fail('times/values length');
      ts.forEach((t, i) => {
        if (!Number.isFinite(t)) fail('bad time');
        const v = checkValue(this.matchName, this.spec, vs[i]);
        const at = this.keys.findIndex(k => Math.abs(k.t - t) < 1e-9);
        const key = { t, v, inI: 'linear', outI: 'linear', spatialZero: false };
        if (at >= 0) this.keys[at] = key; else this.keys.push(key);
      });
      this.keys.sort((a, b) => a.t - b.t);
    }
    keyValue(i) { if (i < 1 || i > this.keys.length) fail('key index'); return this.keys[i - 1].v; }
    setInterpolationTypeAtKey(i, inI, outI) {
      if (i < 1 || i > this.keys.length) fail('key index');
      if (!Object.values(KeyframeInterpolationType).includes(inI) || !Object.values(KeyframeInterpolationType).includes(outI)) fail('bad interpolation');
      Object.assign(this.keys[i - 1], { inI, outI });
    }
    setSpatialAutoBezierAtKey(i) { if (!this.isSpatial) fail('not spatial'); if (i < 1 || i > this.keys.length) fail('key index'); }
    setSpatialContinuousAtKey(i) { if (!this.isSpatial) fail('not spatial'); if (i < 1 || i > this.keys.length) fail('key index'); }
    setSpatialTangentsAtKey(i, a, b) {
      if (!this.isSpatial) fail('not spatial');
      const n = Array.isArray(this.keys[i - 1].v) ? this.keys[i - 1].v.length : 1;
      if (a.length !== n || b.length !== n) fail('tangent dims');
      this.keys[i - 1].spatialZero = a.every(x => x === 0) && b.every(x => x === 0);
    }
    serialize() {
      const out = { v: this.value };
      if (this.keys.length) out.keys = this.keys.map(k => ({ t: k.t, v: k.v, o: k.outI, sz: k.spatialZero }));
      if (this.expression) out.x = this.expression;
      return out;
    }
  }
  class PropertyGroup {
    constructor(mn, parent) {
      this.matchName = mn; this.spec = SCHEMA[mn]; this.parentProperty = parent; this.name = DISPLAY[mn] || mn; this.items = [];
      if (this.spec.kind === 'group') this.fixed = Object.fromEntries(this.spec.children.map(c => [c, make(c, this)]));
    }
    get numProperties() { return this.spec.kind === 'group' ? this.spec.children.length : this.items.length; }
    property(k) {
      if (this.spec.kind === 'group') {
        const c = typeof k === 'number' ? this.fixed[this.spec.children[k - 1]] : this.fixed[k];
        if (!c) fail(`${this.matchName} has no property ${k}`);
        return c;
      }
      const c = typeof k === 'number' ? this.items[k - 1] : this.items.find(x => x.name === k || x.matchName === k);
      if (!c) fail(`${this.matchName} has no property ${k}`);
      return c;
    }
    addProperty(mn) {
      if (this.spec.kind !== 'indexed' || !this.spec.accepts.includes(mn)) fail(`${this.matchName} cannot add ${mn}`);
      const p = make(mn, this); this.items.push(p); return p;
    }
    serialize() {
      if (this.spec.kind === 'indexed') return this.items.map(x => ({ mn: x.matchName, name: x.name, ...x.serialize() }));
      return { props: Object.fromEntries(Object.entries(this.fixed).map(([k, v]) => [k, v.serialize()])) };
    }
  }
  const make = (mn, parent) => {
    const spec = SCHEMA[mn]; if (!spec) fail(`unknown match name ${mn}`);
    return spec.kind === 'prop' ? new Property(mn, parent) : new PropertyGroup(mn, parent);
  };

  let uid = 0;
  class Layer {
    constructor(comp, type, extra = {}) {
      Object.assign(this, { comp, type, id: ++uid, name: type, _parent: null, _start: 0, inPoint: 0, outPoint: comp.duration, motionBlur: false,
        blendingMode: 'normal', label: 0, guideLayer: false, enabled: true, audioEnabled: true, hasAudio: false }, extra);
      this.groups = { 'ADBE Transform Group': make('ADBE Transform Group', null), 'ADBE Marker': make('ADBE Marker', null) };
      if (type === 'shape') this.groups['ADBE Root Vectors Group'] = make('ADBE Root Vectors Group', null);
      if (type !== 'footage-audio') this.groups['ADBE Effect Parade'] = make('ADBE Effect Parade', null);
      const T = this.groups['ADBE Transform Group'].fixed;
      const [w, h] = extra.size || [0, 0];
      T['ADBE Anchor Point'].value = type === 'shape' ? [0, 0] : [w / 2, h / 2];
      T['ADBE Position'].value = [comp.width / 2, comp.height / 2];
    }
    property(k) { const g = this.groups[k]; if (!g) fail(`layer has no ${k}`); return g; }
    get parent() { return this._parent; }
    set parent(p) { if (p && p.comp !== this.comp) fail('parent in another comp'); this._parent = p; }
    setParentWithJump(p) { this.parent = p; }
    setTrackMatte(m, type) {
      if (!Object.values(TrackMatteType).includes(type)) fail('bad track matte type');
      if (!m || m.comp !== this.comp || m === this) fail('bad track matte layer');
      this.matte = { layer: m.id, type };
    }
    get startTime() { return this._start; }
    set startTime(t) { const d = t - this._start; this._start = t; this.inPoint += d; this.outPoint += d; }
    moveToBeginning() { const L = this.comp.layers._list; L.splice(L.indexOf(this), 1); L.unshift(this); }
    serialize(ids) {
      const T = this.groups['ADBE Transform Group'];
      const out = { id: this.id, name: this.name, type: this.type, parent: this._parent ? this._parent.id : null, start: this._start,
        inPoint: this.inPoint, outPoint: this.outPoint, blend: this.blendingMode, enabled: this.enabled, guide: this.guideLayer,
        sep: T.fixed['ADBE Position'].dimensionsSeparated, transform: T.serialize().props, matte: this.matte || null };
      if (this.solid) out.solid = this.solid;
      if (this.source) out.source = this.source.compId || null;
      if (this.groups['ADBE Root Vectors Group']) out.contents = serializeContents(this.groups['ADBE Root Vectors Group']);
      out.effects = this.groups['ADBE Effect Parade'] ? this.groups['ADBE Effect Parade'].items.map(e => ({ mn: e.matchName, props: e.serialize().props })) : [];
      return out;
    }
  }
  function serializeContents(g) {
    return g.items.map(x => {
      if (x.matchName === 'ADBE Vector Group') return { mn: x.matchName, name: x.name, contents: serializeContents(x.fixed['ADBE Vectors Group']), transform: x.fixed['ADBE Vector Transform Group'].serialize().props };
      return { mn: x.matchName, name: x.name, props: x.serialize().props };
    });
  }

  const project = { _items: [], expressionEngine: 'extendscript', bitsPerChannel: 8 };
  class CompItem {
    constructor(name, w, h, par, dur, fps) {
      if (![name, w, h, par, dur, fps].slice(1).every(Number.isFinite)) fail('addComp arguments');
      Object.assign(this, { name, width: w, height: h, pixelAspect: par, duration: dur, frameRate: fps, bgColor: [0, 0, 0], motionBlur: false,
        shutterAngle: 180, shutterPhase: -90, motionBlurSamplesPerFrame: 16, parentFolder: null, compId: 'c' + (++uid) });
      const comp = this;
      this.markerProperty = make('ADBE Marker', null);
      this.layers = {
        _list: [],
        _add(L) { this._list.unshift(L); return L; },
        addShape() { return this._add(new Layer(comp, 'shape')); },
        addNull(d) { return this._add(new Layer(comp, 'null', { size: [100, 100] })); },
        addSolid(color, name, w, h, par, d) {
          if (!Array.isArray(color) || color.length !== 3) fail('addSolid colour must be [r,g,b]');
          if (![w, h].every(v => Number.isInteger(v) && v >= 1 && v <= 30000)) fail('addSolid size must be whole pixels');
          return this._add(new Layer(comp, 'solid', { name, size: [w, h], solid: { color, w, h } }));
        },
        add(item) {
          if (!item || item.folder) fail('layers.add needs a comp or footage item');
          if (item instanceof CompItem) return this._add(new Layer(comp, 'comp', { source: item, size: [item.width, item.height], outPoint: item.duration }));
          return this._add(new Layer(comp, 'footage', { source: item, hasAudio: true }));
        },
        get length() { return this._list.length; }
      };
    }
    openInViewer() {}
    serialize() {
      return { id: this.compId, name: this.name, w: this.width, h: this.height, dur: this.duration, fps: this.frameRate, bg: this.bgColor, motionBlur: this.motionBlur,
        layers: this.layers._list.map(L => L.serialize()), markers: this.markerProperty.keys.map(k => [k.t, k.v.comment]) };
    }
  }
  project.items = {
    addComp(...a) { const c = new CompItem(...a); project._items.push(c); return c; },
    addFolder(name) { const f = { name, parentFolder: null, folder: true }; project._items.push(f); return f; }
  };
  project.importFile = io => {
    if (!io.file.exists) fail('import: missing ' + io.file.fsName);
    const ext = path.extname(io.file.fsName).toLowerCase();
    const src = { hasAlpha: ext === '.png' || ext === '.mov', _alpha: 'ignore', conformFrameRate: 0 };
    Object.defineProperty(src, 'alphaMode', { get() { return this._alpha; }, set(v) { if (!this.hasAlpha) fail('alphaMode on footage without alpha'); if (!Object.values(AlphaMode).includes(v)) fail('bad alphaMode'); this._alpha = v; } });
    const it = { name: path.basename(io.file.fsName), file: io.file.fsName, parentFolder: null, sequence: !!io.sequence, mainSource: src };
    project._items.push(it); log.push('import ' + io.file.fsName + (io.sequence ? ' (sequence)' : '')); return it;
  };

  class File {
    constructor(p) { this.fsName = path.resolve(p); }
    get exists() { return fs.existsSync(this.fsName); }
    get parent() { return new File(path.dirname(this.fsName)); }
  }
  class Folder {
    constructor(p) { this.fsName = path.resolve(p); }
    get exists() { return fs.existsSync(this.fsName) && fs.statSync(this.fsName).isDirectory(); }
    get name() { return path.basename(this.fsName); }
    getFiles(mask) { const re = new RegExp('^' + mask.replace(/\./g, '\\.').replace(/\*/g, '.*') + '$'); return fs.readdirSync(this.fsName).filter(f => re.test(f)).map(f => Object.assign(new File(path.join(this.fsName, f)), { name: f })); }
  }
  class ImportOptions { constructor(f) { this.file = f; this.sequence = false; this.forceAlphabetical = false; } }
  const AlphaMode = { IGNORE: 'ignore', STRAIGHT: 'straight', PREMULTIPLIED: 'premultiplied' };
  const alerts = [];
  const ctx = {
    app: { project, beginUndoGroup() {}, endUndoGroup() {}, newProject() { fail('no project'); } },
    $: { fileName: path.resolve(jsxPath) }, File, Folder, ImportOptions, AlphaMode, TrackMatteType, Shape, MarkerValue, KeyframeInterpolationType, BlendingMode,
    alert: m => alerts.push(m)
  };
  vm.createContext(ctx);
  const src = fs.readFileSync(jsxPath, 'utf8');
  vm.runInContext(src, ctx, { filename: jsxPath });
  if (alerts.length && !allowAlerts) throw new Error('script alerted: ' + alerts.join('\n'));
  const comps = project._items.filter(x => x instanceof CompItem);
  return {
    log, alerts, expressionEngine: project.expressionEngine, bitsPerChannel: project.bitsPerChannel,
    items: project._items.map(x => ({ name: x.name, kind: x instanceof CompItem ? 'comp' : x.folder ? 'folder' : 'footage', folder: x.parentFolder ? x.parentFolder.name : null })),
    comps: comps.map(c => c.serialize())
  };
}
