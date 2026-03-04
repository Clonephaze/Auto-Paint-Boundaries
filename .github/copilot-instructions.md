# Paint Area Limiters — Copilot Instructions

## Project Overview

Blender extension (4.2+) that adds delimiter-constrained face masking to paint modes (Texture, Vertex, Weight). On each brush stroke, the addon raycasts → BFS-expands a face region bounded by user-chosen delimiters → selects those faces via `use_paint_mask` → passes through to the native brush.

## Architecture

```
region_fill/
  __init__.py      — PropertyGroup settings, class registration, keymaps
  delimiter.py     — Operators (auto_select, clear, toggle, toggle_pin) + helpers
  engine.py        — Pure algorithms: bmesh BFS, KDTree symmetry mirroring
  masks.py         — Saved mask presets: save/load/remove/overwrite + UIList
  panel.py         — UI panels nested under VIEW3D_PT_tools_brush_settings
  blender_manifest.toml
```

**Data flow:** LMB keymap → `PAINTLIMIT_OT_auto_select.invoke()` → raycast on evaluated mesh → `engine.get_connected_face_indices()` (bmesh BFS) → `_select_faces()` (numpy foreach_set) → `_flush_selection()` → `PASS_THROUGH` to native brush.

## Critical Patterns

### Evaluated Mesh Flush (the hardest-won lesson)
`mesh.polygons.foreach_set("select", ...)` only writes to the **original** mesh. Paint brushes in Vertex/Weight modes read the **evaluated** mesh. The workaround:
```python
bpy.ops.paint.face_select_all(action='INVERT')  # triggers paintface_flush_flags
bpy.ops.paint.face_select_all(action='INVERT')  # net no-op, but flush happened
```
When replacing an existing mask (e.g. mask_load), toggle `use_paint_mask = False` before writing, then re-enable before flushing.

### Deferred Clear for Texture Paint
Texture Paint captures the mask at stroke start, so clearing mid-event-dispatch crashes (`wm_handler_operator_call`). Use `bpy.app.timers.register(callback, first_interval=0.0)` to defer cleanup. Look up objects by name in the callback — never hold stale references.

### Saved Masks Storage
- Boolean face attributes with dot prefix (`.pal_mask_*`) — hidden from Blender's Attributes panel
- Uniqueness keyed on **attribute names in `mesh.attributes`**, not display names (users can rename freely)
- `PaintAreaMaskItem.attribute_name` stores the immutable key; `.name` is cosmetic

### Operator Namespace
All operators use `paint_limit.*` idname prefix. Classes use `PAINTLIMIT_OT_*` / `PAINTLIMIT_UL_*` / `VIEW3D_PT_paint_area_*`.

### Panel Layout
- `use_property_split = False` on layout (toggle buttons must show icon+label together)
- Only re-enable `use_property_split = True` on specific sub-columns (e.g. the angle slider)
- Panels nest under `VIEW3D_PT_tools_brush_settings` via `bl_parent_id`

## Supported Modes
`SUPPORTED_MODES = {"PAINT_TEXTURE", "PAINT_VERTEX", "PAINT_WEIGHT"}` — defined in `delimiter.py`, imported elsewhere. Sculpt mode is **not supported** (`paint.face_select_all` doesn't exist in sculpt context).

## Build & Test
```powershell
cd region_fill
& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --command extension build
```
Output: `paint_area_limiters-<version>.zip`. Install via Edit → Preferences → Extensions → Install from Disk.

## Keymaps
Registered per paint keymap ("Image Paint", "Vertex Paint", "Weight Paint"):
- **LMB** — replace mask with clicked region
- **Shift+LMB** — add region (additive)
- **Ctrl+LMB** — subtract region
- **D** — toggle limiter on/off
- **Shift+D** — toggle pin mask area

## Conventions
- Every `.py` file has SPDX header + module docstring
- `bmesh` always freed in `try/finally` blocks
- Lazy imports for `bpy_extras`, `engine`, `itertools` (keeps addon load time minimal)
- numpy for bulk face selection read/write (`foreach_get`/`foreach_set`)
- No external dependencies beyond Blender's bundled Python
