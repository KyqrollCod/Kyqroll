(function (DOC) {
  // ExtendScript (ES3): no JSON, no Array.prototype.map, no let/const.
  var MATCH = {
    ell: "ADBE Vector Shape - Ellipse", rect: "ADBE Vector Shape - Rect", path: "ADBE Vector Shape - Group",
    trim: "ADBE Vector Filter - Trim", fill: "ADBE Vector Graphic - Fill", stroke: "ADBE Vector Graphic - Stroke",
    gfill: "ADBE Vector Graphic - G-Fill"
  };
  var BASE = new File($.fileName).parent;

  function toShape(v) {
    var s = new Shape();
    s.vertices = v.v; s.inTangents = v.i; s.outTangents = v.o; s.closed = v.c;
    return s;
  }
  function zeros(n) { var a = []; for (var i = 0; i < n; i++) a.push(0); return a; }

  // a value is a constant, {k: [[time, value], ...], h: [key indices that hold]} or {x: expression, v: base value}
  function setAnim(prop, a, isPath) {
    if (a === undefined || a === null) return;
    var i;
    if (a.x !== undefined) {
      if (a.v !== undefined) prop.setValue(isPath ? toShape(a.v) : a.v);
      prop.expression = a.x;
      return;
    }
    if (a.k !== undefined) {
      var times = [], vals = [];
      for (i = 0; i < a.k.length; i++) { times.push(a.k[i][0]); vals.push(isPath ? toShape(a.k[i][1]) : a.k[i][1]); }
      prop.setValuesAtTimes(times, vals);
      var hold = {};
      if (a.h) for (i = 0; i < a.h.length; i++) hold[a.h[i]] = true;
      var spatial = prop.isSpatial;
      for (i = 1; i <= prop.numKeys; i++) {
        prop.setInterpolationTypeAtKey(i, KeyframeInterpolationType.LINEAR,
          hold[i - 1] ? KeyframeInterpolationType.HOLD : KeyframeInterpolationType.LINEAR);
        if (spatial) {
          // straight lines between position keys, exactly as sampled
          var z = zeros(prop.keyValue(i).length);
          prop.setSpatialAutoBezierAtKey(i, false);
          prop.setSpatialContinuousAtKey(i, false);
          prop.setSpatialTangentsAtKey(i, z, z);
        }
      }
      return;
    }
    prop.setValue(isPath ? toShape(a) : a);
  }

  function setLayerTransform(layer, tr) {
    var T = layer.property("ADBE Transform Group");
    if (tr.a !== undefined) setAnim(T.property("ADBE Anchor Point"), tr.a);
    if (tr.p !== undefined) {
      if (tr.p.sep) {
        T.property("ADBE Position").dimensionsSeparated = true;
        setAnim(T.property("ADBE Position_0"), tr.p.x);
        setAnim(T.property("ADBE Position_1"), tr.p.y);
      } else setAnim(T.property("ADBE Position"), tr.p);
    }
    if (tr.s !== undefined) setAnim(T.property("ADBE Scale"), tr.s);
    if (tr.r !== undefined) setAnim(T.property("ADBE Rotate Z"), tr.r);
    if (tr.o !== undefined) setAnim(T.property("ADBE Opacity"), tr.o);
  }

  function setGroupTransform(T, tr) {
    if (tr.a !== undefined) setAnim(T.property("ADBE Vector Anchor"), tr.a);
    if (tr.p !== undefined) setAnim(T.property("ADBE Vector Position"), tr.p);
    if (tr.s !== undefined) setAnim(T.property("ADBE Vector Scale"), tr.s);
    if (tr.r !== undefined) setAnim(T.property("ADBE Vector Rotation"), tr.r);
    if (tr.o !== undefined) setAnim(T.property("ADBE Vector Group Opacity"), tr.o);
  }

  function addItem(vec, it) {
    var p = vec.addProperty(MATCH[it.t]);
    switch (it.t) {
      case "ell":
        setAnim(p.property("ADBE Vector Ellipse Size"), it.size);
        if (it.pos !== undefined) setAnim(p.property("ADBE Vector Ellipse Position"), it.pos);
        break;
      case "rect":
        setAnim(p.property("ADBE Vector Rect Size"), it.size);
        if (it.pos !== undefined) setAnim(p.property("ADBE Vector Rect Position"), it.pos);
        if (it.round !== undefined) setAnim(p.property("ADBE Vector Rect Roundness"), it.round);
        break;
      case "path":
        setAnim(p.property("ADBE Vector Shape"), it.path, true);
        break;
      case "trim":
        setAnim(p.property("ADBE Vector Trim Start"), it.s);
        setAnim(p.property("ADBE Vector Trim End"), it.e);
        break;
      case "fill":
        setAnim(p.property("ADBE Vector Fill Color"), it.c);
        if (it.o !== undefined) setAnim(p.property("ADBE Vector Fill Opacity"), it.o);
        if (it.rule) p.property("ADBE Vector Fill Rule").setValue(it.rule);
        break;
      case "stroke":
        setAnim(p.property("ADBE Vector Stroke Color"), it.c);
        setAnim(p.property("ADBE Vector Stroke Width"), it.w);
        if (it.o !== undefined) setAnim(p.property("ADBE Vector Stroke Opacity"), it.o);
        p.property("ADBE Vector Stroke Line Cap").setValue(it.cap || 1);
        p.property("ADBE Vector Stroke Line Join").setValue(it.join || 1);
        break;
      case "gfill":
        // AE's default gradient is white to black; the layer's Screen mode turns it into light
        p.property("ADBE Vector Grad Type").setValue(1);
        setAnim(p.property("ADBE Vector Grad Start Pt"), it.sp);
        setAnim(p.property("ADBE Vector Grad End Pt"), it.ep);
        break;
    }
  }

  function addGroups(layer, groups) {
    var contents = layer.property("ADBE Root Vectors Group");
    for (var g = 0; g < groups.length; g++) {
      var d = groups[g];
      var grp = contents.addProperty("ADBE Vector Group");
      grp.name = d.n;
      var vec = grp.property("ADBE Vectors Group");
      for (var i = 0; i < d.items.length; i++) addItem(vec, d.items[i]);
      if (d.tr) setGroupTransform(grp.property("ADBE Vector Transform Group"), d.tr);
    }
  }

  function findFile(rel) {
    var dir = BASE, parts = rel.split("/");
    while (parts.length && parts[0] === "..") { dir = dir.parent; parts.shift(); }
    var f = new File(dir.fsName + "/" + parts.join("/"));
    return f.exists ? f : null;
  }
  function importFile(rel, folder) {
    var f = findFile(rel);
    if (!f) return null;
    var item = app.project.importFile(new ImportOptions(f));
    if (folder) item.parentFolder = folder;
    return item;
  }

  function buildComp(c, made, folder, footFolder) {
    var comp = app.project.items.addComp(c.name, c.w, c.h, 1, c.dur, c.fps);
    comp.parentFolder = folder;
    comp.bgColor = c.bg;
    comp.motionBlur = true;
    comp.shutterAngle = 180;
    comp.shutterPhase = -90;
    comp.motionBlurSamplesPerFrame = 16;
    var layers = {}, list = [], i, d, L;

    // 1. create every layer (bottom to top: AE adds each new layer on top) and parent it
    for (i = 0; i < c.layers.length; i++) {
      d = c.layers[i];
      L = null;
      if (d.t === "null") L = comp.layers.addNull(c.dur);
      else if (d.t === "solid") L = comp.layers.addSolid(d.color, d.n, d.w, d.h, 1, c.dur);
      else if (d.t === "comp") L = comp.layers.add(made[d.src]);
      else if (d.t === "file") {
        var item = importFile(d.file, footFolder);
        if (!item) continue;
        L = comp.layers.add(item);
      } else L = comp.layers.addShape();
      L.name = d.n;
      if (d.parent !== undefined) {
        if (typeof L.setParentWithJump === "function") L.setParentWithJump(layers[d.parent]);
        else L.parent = layers[d.parent];
      }
      if (d.groups) addGroups(L, d.groups);
      if (d.fx) {
        for (var e = 0; e < d.fx.length; e++) {
          var fx = L.property("ADBE Effect Parade").addProperty(d.fx[e].m);
          for (var key in d.fx[e].p) fx.property(key).setValue(d.fx[e].p[key]);
        }
      }
      layers[d.id] = L;
      list.push([L, d]);
    }

    // 2. transforms, after all parenting is in place
    for (i = 0; i < list.length; i++) if (list[i][1].tr) setLayerTransform(list[i][0], list[i][1].tr);

    // 3. switches, timing, labels
    for (i = 0; i < list.length; i++) {
      L = list[i][0]; d = list[i][1];
      if (d.st !== undefined) L.startTime = d.st;
      if (d.outp !== undefined) L.outPoint = d.outp;
      if (d.inp !== undefined) L.inPoint = d.inp;
      if (d.blend === "multiply") L.blendingMode = BlendingMode.MULTIPLY;
      else if (d.blend === "screen") L.blendingMode = BlendingMode.SCREEN;
      if (d.label !== undefined) L.label = d.label;
      if (d.guide) { L.guideLayer = true; L.enabled = false; if (L.hasAudio) L.audioEnabled = false; }
      else if (d.t === "shape" || d.t === "comp" || d.t === "solid") L.motionBlur = true;
      if (d.beats) {
        var M = L.property("ADBE Marker");
        for (var b = 0; b < d.beats; b++) M.setValueAtTime(b * 60 / DOC.bpm, new MarkerValue(b % 4 ? "" : "bar " + (b / 4 + 1)));
      }
      if (d.t === "null") L.moveToBeginning();
    }
    if (c.markers && comp.markerProperty) {
      for (i = 0; i < c.markers.length; i++) comp.markerProperty.setValueAtTime(c.markers[i][0], new MarkerValue(c.markers[i][1]));
    }
    return comp;
  }

  app.beginUndoGroup("Build " + DOC.name);
  try {
    if (!app.project) app.newProject();
    try { app.project.expressionEngine = "javascript-1.0"; } catch (e1) {}
    try { app.project.bitsPerChannel = 16; } catch (e2) {}
    var root = app.project.items.addFolder(DOC.name);
    var scenes = app.project.items.addFolder("Scenes"); scenes.parentFolder = root;
    var foot = app.project.items.addFolder("Footage"); foot.parentFolder = root;
    var made = {}, main = null;
    for (var i = 0; i < DOC.comps.length; i++) {
      var c = DOC.comps[i];
      made[c.id] = buildComp(c, made, c.main ? root : scenes, foot);
      if (c.main) main = made[c.id];
    }
    if (DOC.stems) {
      var stems = app.project.items.addFolder("Audio stems"); stems.parentFolder = foot;
      for (i = 0; i < DOC.stems.length; i++) importFile(DOC.stems[i], stems);
    }
    if (main) { try { main.openInViewer(); } catch (e3) {} }
  } catch (err) {
    alert(DOC.name + ": the build stopped at line " + err.line + "\n" + err.toString());
  }
  app.endUndoGroup();
})(/*__DOC__*/null);
