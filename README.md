# Auto Paint Boundaries

Smart, selection-limited face masking for Blender paint modes.

Auto Paint Boundaries lets you paint **only inside a connected region of faces** defined by boundary rules such as sharp edges, seams, face sets, mesh islands, and more. On each brush stroke it automatically selects a face region under the cursor, enables Blender's native `use_paint_mask`, and passes the stroke through to the active brush.

Supported modes:

* Texture Paint
* Vertex Paint
* Weight Paint

## Features

### One-click auto masking

* Click in the viewport to auto-select a connected face region under the cursor
* Brush strokes are constrained to that region via Blender's face selection mask

### Boundary rules you control

* Single Face
* Mesh Island
* Face Set
* Sharp Edges
* UV Seams
* Crease Edges
* Bevel Weight
* Normal Angle (adjustable threshold)

### Live rule combinations

* Enable multiple boundaries at once (e.g. Sharp + UV Seams)
* "Single Face" always overrides and limits the result to one polygon

### Pinned masks

* Keep the mask between strokes instead of clearing it automatically
* Add or subtract regions while pinned

### Saved masks per object

* Store complex masks as named presets on the mesh
* Recall them later with one click

### Mirror-aware expansion

* Finds mirrored seed faces using a KDTree of face centers
* Respects active X/Y/Z mirror axes

## How It Works (High Level)

On each left-click in a supported paint mode:

1. A hidden operator (`paint_limit.auto_select`) runs *before* the active brush.

2. It raycasts from the mouse into the evaluated mesh to find the clicked face.

3. It performs a **bmesh BFS** from that face, stopping at edges/faces that match the active boundary rules.

4. It writes the resulting face selection back to the original mesh using `foreach_set("select", ...)`.

5. It enables `mesh.use_paint_mask = True`.

6. It forces Blender to flush selection to the evaluated mesh via a double-invert:

   ```python
   bpy.ops.paint.face_select_all(action="INVERT")
   bpy.ops.paint.face_select_all(action="INVERT")
   ```

7. It returns `PASS_THROUGH` so the original brush receives the same click, now constrained by the updated mask.

Texture Paint uses a deferred timer to clear masks safely after the stroke. Vertex and Weight Paint keep the mask visible for the duration of the stroke.

Implementation details:

* `region_fill/delimiter.py` — operators, helpers, mask flushing
* `region_fill/engine.py` — BFS connectivity + symmetry search
* `region_fill/masks.py` — saved mask presets stored as hidden boolean face attributes
* `region_fill/panel.py` — UI panels under **Brush Settings → Auto Boundaries**

## UI & Workflow

The add-on appears in the **Tool** tab of the 3D Viewport sidebar as a child panel under:

> **Brush Settings → Auto Boundaries**

### Main Toggle & Pin

* The panel header includes a checkbox to enable/disable the system
* **Pin Mask Area** (top row):

  * Off: each stroke creates a fresh mask that clears automatically
  * On: masks persist until manually cleared or unpinned
  * Shift+Click adds regions
  * Ctrl+Click subtracts regions

### Boundary Sections

Boundaries are grouped conceptually:

**Topology**

* Single Face
* Mesh Island
* Face Set

**Surface**

* Normal Angle (toggle)
* Angle slider (disabled when Normal Angle is off)

**Edge Attributes**

* Sharp Edges
* UV Seams
* Crease Edges
* Bevel Weight

All boundaries are drawn as icon + label buttons.

## Keymap

For each paint keymap (Image Paint, Vertex Paint, Weight Paint) the add-on registers:

| Gesture     | Operator                  | Effect                              |
| ----------- | ------------------------- | ----------------------------------- |
| LMB         | `paint_limit.auto_select` | Replace mask with clicked region    |
| Shift + LMB | `paint_limit.auto_select` | Add clicked region to existing mask |
| Ctrl + LMB  | `paint_limit.auto_select` | Subtract clicked region from mask   |
| D           | `paint_limit.toggle`      | Toggle Auto Boundaries on/off       |
| Shift + D   | `paint_limit.toggle_pin`  | Toggle Pin Mask Area                |

Keymaps are registered in `region_fill/__init__.py` against:

```python
_KEYMAP_NAMES = ("Image Paint", "Vertex Paint", "Weight Paint")
```

## Saved Masks

Saved masks live under:

> **Brush Settings → Auto Boundaries → Saved Masks**

Each object has a `paint_area_masks` collection and an `active` index.

Each mask (`PaintAreaMaskItem`) stores:

* `name` — user-facing label
* `attribute_name` — hidden mesh attribute key (immutable)

Masks are stored as **boolean face attributes** with a dot prefix:

* `.pal_mask_Mask`
* `.pal_mask_Mask.001`

These are hidden from Blender's Attributes UI (similar to `.sculpt_face_set`).

Buttons:

* **+** — Save Mask: capture current selection
* **–** — Remove Mask: delete preset and mesh attribute
* **Refresh** — Overwrite Mask with current selection
* **Load Mask** — apply selected preset

Loading a mask:

1. Read the boolean attribute into a numpy array
2. Temporarily disable `use_paint_mask`
3. Write face `select` flags
4. Re-enable `use_paint_mask`
5. Run the double-invert flush

## Limitations & Gotchas

* Only supports Texture, Vertex, and Weight Paint
* Relies on face selection masking (`mesh.use_paint_mask`)
* Very high-poly meshes may increase BFS time
* Clearing masks during event dispatch can cause instability; Texture Paint uses `bpy.app.timers.register` for deferred clearing

## Development Notes

* SPDX headers and module docstrings on all `.py` files
* No external dependencies beyond Blender's bundled Python and `numpy`
* `bmesh` objects are freed via `try/finally`

Operator namespace:

* Operators: `paint_limit.*`
* UI list: `PAINTLIMIT_UL_masks`
* Panels: `VIEW3D_PT_paint_area_*`

Supported modes are centralized as `SUPPORTED_MODES` in `delimiter.py`.

### Development Workflow

1. Make changes under `region_fill/`
2. Rebuild with the `extension build` command
3. Reinstall the generated zip in Blender

Pull requests and issues are welcome.
