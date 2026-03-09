# Paint Area Limiters — Copilot Instructions

## Project Overview

Blender extension (4.2+) that adds delimiter-constrained face masking to paint modes (Texture, Vertex, Weight). On each brush stroke, the addon raycasts → BFS-expands a face region bounded by user-chosen delimiters → selects those faces via `use_paint_mask` → passes through to the native brush.

## Architecture

```
auto_paint_boundaries/
  __init__.py      — PropertyGroup settings, class registration, tool registration
  delimiter.py     — Operators (auto_select, clear) + helpers
  engine.py        — Pure algorithms: bmesh BFS, KDTree symmetry mirroring
  masks.py         — Saved mask presets: save/load/remove/overwrite + UIList
  panel.py         — Side-panel UI nested under VIEW3D_PT_tools_brush_settings
  tools.py         — WorkSpaceTool definitions + popover panels for tool header
  blender_manifest.toml
```

**Data flow:** WorkSpaceTool keymap → `PAINTLIMIT_OT_auto_select.invoke()` → BVHTree raycast on original mesh → `engine.get_connected_face_indices()` (bmesh BFS) → `_select_faces()` (numpy foreach_set) → `_flush_selection()` → `PASS_THROUGH` to native brush.

### Activation Modes
Two ways to activate boundary-aware painting:
1. **WorkSpaceTool** (preferred): Select a *Boundary Paint* or *Boundary Fill* tool from the toolbar. Keybinds are scoped to the tool.
2. **Legacy toggle**: Enable `delimiter_enabled` checkbox in the side-panel header. Works with any brush/tool.

`PAINTLIMIT_OT_auto_select.poll()` returns `True` when *either* path is active.

## Critical Patterns

### Evaluated Mesh Flush (the hardest-won lesson)
`mesh.polygons.foreach_set("select", ...)` only writes to the **original** mesh. Paint brushes in Vertex/Weight modes read the **evaluated** mesh. The workaround:
```python
bpy.ops.paint.face_select_all(action='INVERT')  # triggers paintface_flush_flags
bpy.ops.paint.face_select_all(action='INVERT')  # net no-op, but flush happened
```
When replacing an existing mask (e.g. mask_load), toggle `use_paint_mask = False` before writing, then re-enable before flushing.

### BVHTree Raycast (topology modifier safety)
Never use `obj.ray_cast()` or `obj_eval.ray_cast()` — both return evaluated-mesh face indices that can be out-of-range on the original mesh (e.g. with Subdivision Surface). Use `BVHTree.FromBMesh(bm)` built from the **original** mesh instead.

### TBB Race Condition (the second hardest-won lesson)
Writing to `mesh.polygons` (even `foreach_set` without `mesh.update()`) fires RNA depsgraph dirty notifications that race with TBB paint workers in `project_face_seams_init`, causing `EXCEPTION_ACCESS_VIOLATION`. The safe deferred clear (`_clear_mask`) only sets `obj.data.use_paint_mask = False` — no polygon writes. Full clears (`_full_clear_mask`) are only safe from user-initiated actions (panel buttons) when no stroke is active.

### Deferred Clear for Texture Paint
Texture Paint captures the mask at stroke start, so clearing mid-event-dispatch crashes (`wm_handler_operator_call`). Use `bpy.app.timers.register(callback, first_interval=0.0)` to defer cleanup. Look up objects by name in the callback — never hold stale references.

### Topology Modifier Guard
When unapplied modifiers change face topology (Subdivision, Remesh, etc.), `pin_mask_area` is auto-enabled on use and a warning is shown in the panel. Without pin, the deferred clear races with TBB workers.

### Saved Masks Storage
- Boolean face attributes with dot prefix (`.pal_mask_*`) — hidden from Blender's Attributes panel
- Uniqueness keyed on **attribute names in `mesh.attributes`**, not display names (users can rename freely)
- `PaintAreaMaskItem.attribute_name` stores the immutable key; `.name` is cosmetic

### Operator Namespace
All operators use `paint_limit.*` idname prefix. Classes use `PAINTLIMIT_OT_*` / `PAINTLIMIT_UL_*` / `VIEW3D_PT_paint_area_*`.

### WorkSpaceTool Naming
Tool idnames: `paint_limit.boundary_paint`, `paint_limit.boundary_fill`. Per-mode classes append the mode suffix (e.g. `BoundaryPaintTexture`). Registered/unregistered via `bpy.utils.register_tool()`/`unregister_tool()`.

### Panel Layout
- `use_property_split = False` on layout (toggle buttons must show icon+label together)
- Only re-enable `use_property_split = True` on specific sub-columns (e.g. the angle slider)
- Side panels nest under `VIEW3D_PT_tools_brush_settings` via `bl_parent_id`
- Popover panels (`VIEW3D_PT_boundary_delimiters`, `VIEW3D_PT_boundary_masks`) appear in tool header when a boundary tool is active

## Supported Modes
`SUPPORTED_MODES = {"PAINT_TEXTURE", "PAINT_VERTEX", "PAINT_WEIGHT"}` — defined in `delimiter.py`, imported elsewhere. Sculpt mode is **not supported** (`paint.face_select_all` doesn't exist in sculpt context).

## Build & Test
```powershell
cd auto_paint_boundaries
& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --command extension build
```
Output: `auto_paint_boundaries-<version>.zip`. Install via Edit → Preferences → Extensions → Install from Disk.

## Keymaps (scoped to WorkSpaceTool)
- **LMB** — replace mask with clicked region
- **Shift+LMB** — add region (additive)
- **Ctrl+LMB** — subtract region
- **Ctrl+Shift+LMB** — replace mask (consumes event, returns FINISHED)

## Conventions
- Every `.py` file has SPDX header + module docstring
- `bmesh` always freed in `try/finally` blocks
- Lazy imports for `bpy_extras`, `engine`, `itertools` (keeps addon load time minimal)
- numpy for bulk face selection read/write (`foreach_get`/`foreach_set`)
- No external dependencies beyond Blender's bundled Python
