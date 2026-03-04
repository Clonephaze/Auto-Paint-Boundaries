# Auto Paint Boundaries — boundary-aware face masking for Blender.
# Copyright (C) 2026 Jack Smith/Clonephaze
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Saved face-mask presets.

Stores named boolean face attributes on the mesh so users can save and
recall complex face selections with one click.  Attribute names are
dot-prefixed (``.pal_mask_*``) so they stay hidden from the generic
Attributes panel, matching the convention Blender uses for internal
data like ``.sculpt_face_set``.
"""

import numpy as np
import bpy

# Prefix for attribute names — dot prefix hides them from the UI.
_ATTR_PREFIX = ".pal_mask_"


# ===================================================================
#  Helpers
# ===================================================================


def _attr_name(display_name: str) -> str:
    """Convert a user-facing display name to an attribute name."""
    return _ATTR_PREFIX + display_name


def _get_selection(mesh) -> np.ndarray:
    """Return the current face selection as a boolean array."""
    n = len(mesh.polygons)
    sel = np.zeros(n, dtype=bool)
    mesh.polygons.foreach_get("select", sel)
    return sel


def _set_selection(mesh, sel: np.ndarray):
    """Apply a boolean array as the face selection."""
    mesh.polygons.foreach_set("select", sel)
    mesh.update()


def _flush_selection():
    """Flush face selection to the evaluated mesh (double-invert trick)."""
    bpy.ops.paint.face_select_all(action='INVERT')
    bpy.ops.paint.face_select_all(action='INVERT')


# ===================================================================
#  Operators
# ===================================================================


class PAINTLIMIT_OT_mask_save(bpy.types.Operator):
    """Save the current face selection as a named mask preset"""

    bl_idname = "paint_limit.mask_save"
    bl_label = "Save Mask"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        return obj.data.use_paint_mask

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        masks = obj.paint_area_masks

        # Find a unique attribute key based on existing mesh attributes,
        # NOT display names (which the user can rename freely).
        base_attr = _ATTR_PREFIX + "Mask"
        existing_attrs = {a.name for a in mesh.attributes}
        attr_key = base_attr
        counter = 1
        while attr_key in existing_attrs:
            attr_key = f"{base_attr}.{counter:03d}"
            counter += 1

        # Derive a display name from the unique key.
        display_name = attr_key[len(_ATTR_PREFIX):]

        # Store selection as a boolean face attribute.
        sel = _get_selection(mesh)
        attr = mesh.attributes.new(
            name=attr_key, type='BOOLEAN', domain='FACE',
        )
        attr.data.foreach_set("value", sel)

        # Add to the collection and make it active.
        item = masks.add()
        item.name = display_name
        item.attribute_name = attr_key
        obj.paint_area_masks_active = len(masks) - 1

        return {'FINISHED'}


class PAINTLIMIT_OT_mask_load(bpy.types.Operator):
    """Load the selected mask preset onto the face selection"""

    bl_idname = "paint_limit.mask_load"
    bl_label = "Load Mask"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        return 0 <= idx < len(masks)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        item = masks[idx]

        attr_key = item.attribute_name
        attr = mesh.attributes.get(attr_key)
        if attr is None:
            self.report({'WARNING'}, f"Attribute missing for \"{item.name}\"")
            return {'CANCELLED'}

        n = len(mesh.polygons)
        sel = np.zeros(n, dtype=bool)
        attr.data.foreach_get("value", sel)

        # Disable paint mask first so the evaluated mesh is invalidated,
        # then write the new selection and re-enable.  Without this
        # toggle the double-invert flush sees stale evaluated data.
        mesh.use_paint_mask = False
        _set_selection(mesh, sel)
        mesh.use_paint_mask = True
        _flush_selection()

        return {'FINISHED'}


class PAINTLIMIT_OT_mask_remove(bpy.types.Operator):
    """Remove the selected mask preset"""

    bl_idname = "paint_limit.mask_remove"
    bl_label = "Remove Mask"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        return 0 <= idx < len(masks)

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        item = masks[idx]

        # Remove the underlying attribute.
        attr_key = item.attribute_name
        attr = mesh.attributes.get(attr_key)
        if attr is not None:
            mesh.attributes.remove(attr)

        masks.remove(idx)

        # Keep the active index in range.
        obj.paint_area_masks_active = min(idx, len(masks) - 1)

        return {'FINISHED'}


class PAINTLIMIT_OT_mask_overwrite(bpy.types.Operator):
    """Overwrite the selected mask preset with the current selection"""

    bl_idname = "paint_limit.mask_overwrite"
    bl_label = "Overwrite Mask"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        if not (0 <= idx < len(masks)):
            return False
        return obj.data.use_paint_mask

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        item = masks[idx]

        attr_key = item.attribute_name
        sel = _get_selection(mesh)

        if attr_key in mesh.attributes:
            attr = mesh.attributes[attr_key]
        else:
            attr = mesh.attributes.new(
                name=attr_key, type='BOOLEAN', domain='FACE',
            )

        attr.data.foreach_set("value", sel)

        return {'FINISHED'}


# ===================================================================
#  UIList
# ===================================================================


class PAINTLIMIT_UL_masks(bpy.types.UIList):
    """List of saved mask presets."""

    bl_idname = "PAINTLIMIT_UL_masks"

    def draw_item(self, _context, layout, _data, item, _icon,
                  _active_data, _active_propname, _index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False,
                        icon='MOD_MASK')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='MOD_MASK')
