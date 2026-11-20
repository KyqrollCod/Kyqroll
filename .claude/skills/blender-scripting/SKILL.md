---
name: blender-scripting
description: Build 3D scenes, models and animations as parameterized Blender Python (bpy) scripts instead of manual modeling, e.g. mechanical assemblies, product shots, procedural objects, camera moves, batch variations or renders. Use when the user asks for a 3D model/scene/animation, a Blender script, or many variations of a 3D asset.
---

# blender-scripting: scene as code, Blender as the renderer

Source idea: "Claude Code vs Blender" post (2026-10). The point is not that AI replaces
Blender. Repetitive manual work (model → position → materials/lights/camera → animate →
redo when specs change) becomes a **reproducible, parameterized script**. When specs
change, edit a parameter and rebuild instead of remodeling.

## Script structure
1. **Parameters block at the top** (dataclass/dict): dimensions, counts (e.g. blade
   count per stage), speeds, materials, camera path, frame range, render settings.
2. **Modular builder functions**, one per component (`build_fan()`, `build_compressor_stage(n)`,
   `build_shaft()`), each returning objects under a named collection. Parent moving parts
   to empties so rotation is controlled by a variable.
3. **Materials** as functions (principled BSDF params: metallic, roughness, color).
4. **Animation** driven by parameters (keyframes or drivers): independent shaft speeds,
   camera orbit via an empty + Track To constraint, cyclic F-curve modifiers for loops.
5. **Lighting/camera/render setup** separate from geometry.
6. `main()` clears the scene (or only its own collection), builds everything, and optionally
   saves `.blend` and renders.

## Running and verifying
- Headless: `blender -b -P scene.py -- --blades 24 --out out/` (parse args after `--`).
  Render a still: `-f 1`. Animation: `-a`. Use EEVEE/low samples for previews, Cycles for finals.
- Verify by rendering a low-res preview frame and **looking at the image** (Read the PNG)
  before reporting done; check object counts and that animation actually moves (compare
  two frames). If Blender isn't installed, say so, deliver the script and the exact run
  command, and don't claim it was rendered.
- Variations = loop over parameter sets and write each output to its own file.

## Prompt template (from the source)
"Generate a Blender Python script for <object> with separate <components>,
parameterized <counts/sizes>, independent <motions>, <materials>, and a cinematic camera
orbit. Keep geometry modular and expose the main parameters so variations can be
regenerated without remodeling."
