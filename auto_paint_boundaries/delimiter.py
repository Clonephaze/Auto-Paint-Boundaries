# Auto Paint Boundaries — boundary-aware face masking for Blender.
# Copyright (C) 2026 Jack Smith/Clonephaze
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto-boundary operator for brush stroke constraining.

``PAINTLIMIT_OT_auto_select``
    Fires on LMB *before* the built-in brush.  Raycasts to find the
    face under the cursor, BFS-expands using the active boundaries,
    selects those faces on the mesh, and enables ``use_paint_mask``.
    Returns ``PASS_THROUGH`` so the brush receives the same click and
    paints — but only on the selected faces.

    When *Pin Mask Area* is **off** (the default), a deferred timer
    clears the mask shortly after the click, so the selection overlay
    is never visible in practice.
"""

import numpy as np
import bpy

# Modes where the limiter is active.
SUPPORTED_MODES = {"PAINT_TEXTURE", "PAINT_VERTEX", "PAINT_WEIGHT"}


# ===================================================================
#  Helpers
# ===================================================================


def _resolve_viewport(context, event):
    """Return *(region, rv3d)* for the 3-D viewport under the mouse."""
    for area in context.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for reg in area.regions:
            if (
                reg.type == "WINDOW"
                and reg.x <= event.mouse_x < reg.x + reg.width
                and reg.y <= event.mouse_y < reg.y + reg.height
            ):
                return reg, area.spaces.active.region_3d
    return None, None


def _raycast_face(context, event, obj):
    """Raycast and return the face index hit, or -1 on miss."""
    from bpy_extras import view3d_utils

    region, rv3d = _resolve_viewport(context, event)
    if region is None:
        return -1

    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    mat_inv = obj.matrix_world.inverted()
    local_origin = mat_inv @ ray_origin
    local_dir = (mat_inv.to_3x3() @ ray_dir).normalized()

    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)

    success, _location, _normal, face_index = obj_eval.ray_cast(
        local_origin, local_dir,
    )
    return face_index if success else -1


def _select_faces(mesh, face_indices, additive=False, subtract=False):
    """Select faces on the mesh.  When *additive* is True, add to the
    existing selection.  When *subtract* is True, remove from it."""
    n = len(mesh.polygons)
    if additive or subtract:
        sel = np.zeros(n, dtype=bool)
        mesh.polygons.foreach_get("select", sel)
    else:
        sel = np.zeros(n, dtype=bool)
    for fi in face_indices:
        if 0 <= fi < n:
            if subtract:
                sel[fi] = False
            else:
                sel[fi] = True
    mesh.polygons.foreach_set("select", sel)
    mesh.update()


def _flush_selection():
    """Flush face-selection flags to the evaluated mesh.

    Blender's built-in ``face_select_all`` operator internally calls
    ``paintface_flush_flags`` which copies face selection from the
    original mesh to the evaluated mesh.  There is no direct Python
    binding for that C function, so we trigger it by inverting the
    selection twice — a logical no-op that forces the flush.
    """
    bpy.ops.paint.face_select_all(action='INVERT')
    bpy.ops.paint.face_select_all(action='INVERT')


def _clear_mask(obj):
    """Disable paint mask and deselect all faces."""
    mesh = obj.data
    mesh.use_paint_mask = False
    n = len(mesh.polygons)
    sel = np.zeros(n, dtype=bool)
    mesh.polygons.foreach_set("select", sel)
    mesh.update()


def _schedule_clear(obj_name):
    """Schedule a mask clear on a zero-second timer.

    Running ``_clear_mask`` inside a modal handler during the event
    dispatch chain causes an access-violation crash in
    ``wm_handler_operator_call``.  By deferring the clear to a timer
    callback we run *after* the event handler stack has fully unwound,
    which is safe.
    """
    def _deferred_clear():
        obj = bpy.data.objects.get(obj_name)
        if obj is not None and obj.type == "MESH":
            _clear_mask(obj)
        return None  # don't repeat
    bpy.app.timers.register(_deferred_clear, first_interval=0.0)


# ===================================================================
#  Auto-select operator
# ===================================================================


class PAINTLIMIT_OT_auto_select(bpy.types.Operator):
    """Automatically select boundary-constrained faces before a brush
    stroke, so the built-in brush only paints within the boundary.
    """

    bl_idname = "paint_limit.auto_select"
    bl_label = "Auto-Select Boundary Region"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        if context.mode not in SUPPORTED_MODES:
            return False
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        # Only fire when Auto Boundaries is enabled
        settings = getattr(context.scene, "paint_area_limiters", None)
        if settings is None:
            return False
        return settings.delimiter_enabled

    # ----- invoke --------------------------------------------------------

    def invoke(self, context, event):
        from .engine import get_connected_face_indices, find_mirror_seeds

        obj = context.active_object
        settings = context.scene.paint_area_limiters
        mesh = obj.data

        additive = event.shift
        subtract = event.ctrl

        # When the mask is pinned and already active, plain LMB should
        # just paint on the existing mask — don't replace it.
        # Shift+LMB still extends the pinned mask.
        # Ctrl+LMB still subtracts from the pinned mask.
        if settings.pin_mask_area and mesh.use_paint_mask and not additive and not subtract:
            return {"PASS_THROUGH"}

        face_index = _raycast_face(context, event, obj)
        if face_index < 0:
            # Missed the mesh — don't change selection, pass through
            return {"PASS_THROUGH"}

        # Build the set of active boundaries from individual toggles.
        delimiters = set()
        if settings.use_single_face:
            delimiters.add("FACE")
        if settings.use_sharp:
            delimiters.add("SHARP")
        if settings.use_uv_island:
            delimiters.add("UV_ISLAND")
        if settings.use_normal:
            delimiters.add("NORMAL")
        if settings.use_face_set:
            delimiters.add("FACE_SET")
        if settings.use_crease:
            delimiters.add("CREASE")
        if settings.use_bevel:
            delimiters.add("BEVEL")
        if settings.use_mesh_island:
            delimiters.add("MESH_ISLAND")

        # Nothing enabled — treat as unconstrained (whole mesh island).
        if not delimiters:
            delimiters.add("MESH_ISLAND")

        # Single Face always wins — skip BFS entirely.
        if "FACE" in delimiters:
            face_indices = {face_index}
        else:
            face_indices = get_connected_face_indices(
                mesh, face_index, delimiters,
                normal_angle=settings.normal_angle,
            )

        # Symmetry: BFS from mirrored seed faces too.
        mx, my, mz = mesh.use_mirror_x, mesh.use_mirror_y, mesh.use_mirror_z
        if mx or my or mz:
            for mseed in find_mirror_seeds(mesh, face_index, mx, my, mz):
                face_indices |= get_connected_face_indices(
                    mesh, mseed, delimiters,
                    normal_angle=settings.normal_angle,
                )

        _select_faces(mesh, face_indices, additive=additive, subtract=subtract)

        # Enable native face selection masking
        mesh.use_paint_mask = True

        # Flush selection to the evaluated mesh so paint brushes in
        # all modes (not just Texture Paint) see the change.
        _flush_selection()

        # In Texture Paint, the brush captures the mask at stroke start,
        # so we can clear it immediately after — hiding the gray overlay.
        # Vertex / Weight Paint re-read the mask every frame, so the
        # mask must stay active (and visible) throughout the stroke.
        if not settings.pin_mask_area and context.mode == "PAINT_TEXTURE":
            _schedule_clear(obj.name)

        return {"PASS_THROUGH"}


# ===================================================================
#  Clear delimiter selection
# ===================================================================


class PAINTLIMIT_OT_clear(bpy.types.Operator):
    """Clear the boundary face selection and disable face masking."""

    bl_idname = "paint_limit.clear"
    bl_label = "Clear Selection"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        if context.mode not in SUPPORTED_MODES:
            return False
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        _clear_mask(context.active_object)
        return {"FINISHED"}


# ===================================================================
#  Toggle limiter on/off
# ===================================================================


class PAINTLIMIT_OT_toggle(bpy.types.Operator):
    """Toggle Auto Boundaries on or off."""

    bl_idname = "paint_limit.toggle"
    bl_label = "Toggle Auto Boundaries"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        if context.mode not in SUPPORTED_MODES:
            return False
        settings = getattr(context.scene, "paint_area_limiters", None)
        return settings is not None

    def execute(self, context):
        settings = context.scene.paint_area_limiters
        settings.delimiter_enabled = not settings.delimiter_enabled
        # When disabling, clear any lingering mask
        if not settings.delimiter_enabled:
            obj = context.active_object
            if obj is not None and obj.type == "MESH":
                _clear_mask(obj)
        return {"FINISHED"}


# ===================================================================
#  Toggle pin mask area
# ===================================================================


class PAINTLIMIT_OT_toggle_pin(bpy.types.Operator):
    """Toggle Pin Mask Area on or off."""

    bl_idname = "paint_limit.toggle_pin"
    bl_label = "Toggle Pin Mask Area"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        if context.mode not in SUPPORTED_MODES:
            return False
        settings = getattr(context.scene, "paint_area_limiters", None)
        return settings is not None

    def execute(self, context):
        settings = context.scene.paint_area_limiters
        settings.pin_mask_area = not settings.pin_mask_area
        # When un-pinning, clear the mask so next stroke starts fresh
        if not settings.pin_mask_area:
            obj = context.active_object
            if obj is not None and obj.type == "MESH":
                _clear_mask(obj)
        return {"FINISHED"}
