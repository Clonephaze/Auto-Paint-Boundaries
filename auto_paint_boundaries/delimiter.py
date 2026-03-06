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


def _has_topology_modifiers(context, obj):
    """Return True if the modifier stack changes the face count.

    When the evaluated mesh has more (or fewer) faces than ``obj.data``,
    any write from Python to the original mesh triggers a depsgraph dirty
    notification on the separate evaluated copy.  Blender's TBB paint
    workers may be reading that evaluated copy concurrently, causing an
    access-violation crash in ``project_face_seams_init``.
    """
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    return len(obj_eval.data.polygons) != len(obj.data.polygons)


def _raycast_face(context, event, obj):
    """Raycast and return the face index hit, or -1 on miss.

    Uses a BVHTree built from ``obj.data`` (the original, unmodified
    mesh) so the returned face index is always valid for
    ``obj.data.polygons``.  ``Object.ray_cast`` and variants silently
    evaluate modifiers and return indices from the subdivided mesh.
    """
    from bpy_extras import view3d_utils
    from mathutils.bvhtree import BVHTree
    import bmesh

    region, rv3d = _resolve_viewport(context, event)
    if region is None:
        return -1

    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    mat_inv = obj.matrix_world.inverted()
    local_origin = mat_inv @ ray_origin
    local_dir = (mat_inv.to_3x3() @ ray_dir).normalized()

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bvh = BVHTree.FromBMesh(bm)
    finally:
        bm.free()

    _location, _normal, face_index, _dist = bvh.ray_cast(local_origin, local_dir)
    return face_index if face_index is not None else -1


def _select_faces(mesh, face_indices, additive=False, subtract=False):
    """Select faces on the mesh.  When *additive* is True, add to the
    existing selection.  When *subtract* is True, remove from it.

    Does **not** call ``mesh.update()`` — that triggers a depsgraph
    re-evaluation which races with brush stroke initialisation and
    causes partially-applied masks.  ``_flush_selection()`` is called
    separately afterward and is all that's needed to sync selection
    flags to the evaluated mesh.
    """
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
    """Hide the paint-mask overlay by disabling ``use_paint_mask``.

    Does **not** write to ``mesh.polygons`` or call ``mesh.update()``.
    Any mesh data write during an active brush stroke (even via a
    deferred timer) invalidates the evaluated mesh that the paint
    system's TBB workers are actively reading, causing partially-
    applied masks or outright crashes.

    The stale face-select bits are invisible when ``use_paint_mask``
    is False and are unconditionally overwritten by ``_select_faces``
    at the start of the next stroke.
    """
    obj.data.use_paint_mask = False


def _full_clear_mask(obj):
    """Fully clear the mask: deselect all faces and disable the overlay.

    Safe to call from user-initiated operators (panel buttons, hotkeys)
    where no brush stroke is active.  Must **not** be called from a
    deferred timer during a stroke — use ``_clear_mask`` for that.
    """
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

        additive = event.shift and not event.ctrl
        subtract = event.ctrl and not event.shift
        replace = event.shift and event.ctrl

        # When the mask is pinned and already active, plain LMB should
        # just paint on the existing mask — don't replace it.
        # Alt+LMB replaces the pinned mask with a new region.
        # Shift+LMB still extends the pinned mask.
        # Ctrl+LMB still subtracts from the pinned mask.
        if settings.pin_mask_area and mesh.use_paint_mask and not additive and not subtract and not replace:
            return {"PASS_THROUGH"}

        # Guard: if unapplied modifiers change the face count *and* pin
        # is off, the deferred _clear_mask races with Blender's TBB paint
        # workers on the evaluated mesh copy and crashes.  Auto-enable
        # pin so the user can keep working without applying modifiers.
        if not settings.pin_mask_area and _has_topology_modifiers(context, obj):
            settings.pin_mask_area = True

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

        # Replace (Ctrl+Shift+LMB) only swaps the mask — consume the
        # event so the native brush doesn't also fire with Ctrl held
        # (which would erase/deselect the face under the cursor).
        if replace:
            return {"FINISHED"}

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
        obj = context.active_object
        _full_clear_mask(obj)
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
                _full_clear_mask(obj)
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
                _full_clear_mask(obj)
        return {"FINISHED"}
