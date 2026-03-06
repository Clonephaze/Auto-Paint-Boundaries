# Auto Paint Boundaries — boundary-aware face masking for Blender.
# Copyright (C) 2026 Jack Smith/Clonephaze
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Auto Paint Boundaries — a Blender add-on that adds boundary-constrained
face masking to paint modes (Texture, Vertex, Weight).

Enable *Limit to Faces* in the sidebar panel.  Choose a boundary type.
When you start a brush stroke, the addon automatically selects the
connected face region under the cursor and constrains the brush to
those faces using Blender's native face-selection mask.
"""

import bpy

from .delimiter import (
    PAINTLIMIT_OT_auto_select,
    PAINTLIMIT_OT_clear,
    PAINTLIMIT_OT_toggle,
    PAINTLIMIT_OT_toggle_pin,
)
from .masks import (
    PAINTLIMIT_OT_mask_load,
    PAINTLIMIT_OT_mask_overwrite,
    PAINTLIMIT_OT_mask_remove,
    PAINTLIMIT_OT_mask_save,
    PAINTLIMIT_UL_masks,
)
from .panel import VIEW3D_PT_paint_area_limiters, VIEW3D_PT_paint_area_saved_masks

# Keymap items registered in the addon keyconfig (cleaned up in unregister).
_addon_keymaps: list[tuple] = []


# ===================================================================
#  Scene-level settings
# ===================================================================


def _on_pin_mask_update(self, context):
    """Clear the face mask when the user un-pins via the checkbox."""
    if not self.pin_mask_area:
        obj = context.active_object
        if obj is not None and obj.type == "MESH" and obj.data.use_paint_mask:
            from .delimiter import _clear_mask
            _clear_mask(obj)


class PaintAreaLimiterSettings(bpy.types.PropertyGroup):
    """Global boundary settings, shared by all tools."""

    delimiter_enabled: bpy.props.BoolProperty(
        name="Limit to Faces",
        description=(
            "Automatically constrain brush strokes to a connected face "
            "region based on the active boundary types"
        ),
        default=False,
    )

    # -- Individual boundary toggles (single column of depressed buttons) --

    use_single_face: bpy.props.BoolProperty(
        name="Single Face",
        description="Constrain to the single clicked face",
        default=True,
    )
    use_sharp: bpy.props.BoolProperty(
        name="Sharp Edges",
        description="Stop at edges marked as sharp",
        default=False,
    )
    use_uv_island: bpy.props.BoolProperty(
        name="UV Seams",
        description="Stop at UV seam edges",
        default=False,
    )
    use_normal: bpy.props.BoolProperty(
        name="Normal Angle",
        description="Stop where neighbouring face normals diverge",
        default=False,
    )
    use_face_set: bpy.props.BoolProperty(
        name="Face Set",
        description="Stop at face-set boundaries",
        default=False,
    )
    use_crease: bpy.props.BoolProperty(
        name="Crease Edges",
        description="Stop at edges with crease weight",
        default=False,
    )
    use_bevel: bpy.props.BoolProperty(
        name="Bevel Weight",
        description="Stop at edges with bevel weight",
        default=False,
    )
    use_mesh_island: bpy.props.BoolProperty(
        name="Mesh Island",
        description="Expand to the entire disconnected mesh piece (no boundary)",
        default=False,
    )

    normal_angle: bpy.props.FloatProperty(
        name="Angle",
        description="Maximum angle between face normals before the boundary stops",
        subtype="ANGLE",
        min=0.0,
        max=3.14159,
        default=0.5236,  # 30 degrees
    )

    pin_mask_area: bpy.props.BoolProperty(
        name="Pin Mask Area",
        description=(
            "Keep the face mask between brush strokes instead of "
            "clearing it automatically after each stroke.\n"
            "Shift+Click to add regions, Ctrl+Click to subtract"
        ),
        default=False,
        update=_on_pin_mask_update,
    )


# ===================================================================
#  Registration
# ===================================================================

class PaintAreaMaskItem(bpy.types.PropertyGroup):
    """A single saved mask preset."""
    name: bpy.props.StringProperty(name="Name", default="Mask")
    attribute_name: bpy.props.StringProperty(
        description="Internal mesh attribute key (set once at creation)",
    )


_classes = (
    PaintAreaMaskItem,
    PaintAreaLimiterSettings,
    PAINTLIMIT_OT_auto_select,
    PAINTLIMIT_OT_clear,
    PAINTLIMIT_OT_toggle,
    PAINTLIMIT_OT_toggle_pin,
    PAINTLIMIT_OT_mask_save,
    PAINTLIMIT_OT_mask_load,
    PAINTLIMIT_OT_mask_remove,
    PAINTLIMIT_OT_mask_overwrite,
    PAINTLIMIT_UL_masks,
    VIEW3D_PT_paint_area_limiters,
    VIEW3D_PT_paint_area_saved_masks,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.paint_area_limiters = bpy.props.PointerProperty(
        type=PaintAreaLimiterSettings,
    )
    bpy.types.Object.paint_area_masks = bpy.props.CollectionProperty(
        type=PaintAreaMaskItem,
    )
    bpy.types.Object.paint_area_masks_active = bpy.props.IntProperty()

    # -- Keymap registration -----------------------------------------------
    # Addon keyconfig items are checked before default keyconfig items.
    # Register in every supported paint / sculpt keymap.
    _KEYMAP_NAMES = ("Image Paint", "Vertex Paint", "Weight Paint")
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        for km_name in _KEYMAP_NAMES:
            km = kc.keymaps.new(name=km_name, space_type='EMPTY')
            # LMB — replace mask with clicked region
            kmi = km.keymap_items.new(
                "paint_limit.auto_select", 'LEFTMOUSE', 'PRESS',
            )
            _addon_keymaps.append((km, kmi))
            # Shift+LMB — add clicked region to existing mask
            kmi = km.keymap_items.new(
                "paint_limit.auto_select", 'LEFTMOUSE', 'PRESS',
                shift=True,
            )
            _addon_keymaps.append((km, kmi))
            # Ctrl+LMB — subtract clicked region from existing mask
            kmi = km.keymap_items.new(
                "paint_limit.auto_select", 'LEFTMOUSE', 'PRESS',
                ctrl=True,
            )
            _addon_keymaps.append((km, kmi))
            # Alt+LMB — replace pinned mask with new region
            kmi = km.keymap_items.new(
                "paint_limit.auto_select", 'LEFTMOUSE', 'PRESS',
                ctrl=True, shift=True,
            )
            _addon_keymaps.append((km, kmi))
            # D — toggle limiter on/off
            kmi = km.keymap_items.new(
                "paint_limit.toggle", 'D', 'PRESS',
            )
            _addon_keymaps.append((km, kmi))
            # Shift+D — toggle pin mask area
            kmi = km.keymap_items.new(
                "paint_limit.toggle_pin", 'D', 'PRESS',
                shift=True,
            )
            _addon_keymaps.append((km, kmi))


def unregister():

    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    del bpy.types.Object.paint_area_masks_active
    del bpy.types.Object.paint_area_masks
    del bpy.types.Scene.paint_area_limiters

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
