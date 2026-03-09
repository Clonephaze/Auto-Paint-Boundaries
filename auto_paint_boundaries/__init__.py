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
from .panel import (
    VIEW3D_PT_paint_area_limiters,
    VIEW3D_PT_paint_area_saved_masks,
    VIEW3D_PT_boundary_delimiters,
    VIEW3D_PT_boundary_masks,
    draw_tool_header,
)

# Keymap items registered in the addon keyconfig (cleaned up in unregister).
_addon_keymaps: list[tuple] = []
# Shortcut keymaps for toggle/clear (drawn in addon preferences).
_shortcut_keymaps: list[tuple] = []


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
            "Enable boundary-aware painting. Brush strokes are "
            "automatically constrained to a connected face region "
            "based on the active boundary types"
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
            "When pinned, Shift+Click adds regions and "
            "Ctrl+Click subtracts them"
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


# ===================================================================
#  Addon Preferences
# ===================================================================


class PaintAreaLimiterPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # -- Startup defaults --------------------------------------------------

    default_enabled: bpy.props.BoolProperty(
        name="Enable Boundaries",
        description="Start with boundary-aware painting enabled",
        default=False,
    )
    default_pin_mask: bpy.props.BoolProperty(
        name="Pin Mask Area",
        description="Start with mask pinning enabled",
        default=False,
    )
    default_use_single_face: bpy.props.BoolProperty(
        name="Single Face", default=True,
    )
    default_use_sharp: bpy.props.BoolProperty(
        name="Sharp Edges", default=False,
    )
    default_use_uv_island: bpy.props.BoolProperty(
        name="UV Seams", default=False,
    )
    default_use_normal: bpy.props.BoolProperty(
        name="Normal Angle", default=False,
    )
    default_use_face_set: bpy.props.BoolProperty(
        name="Face Set", default=False,
    )
    default_use_crease: bpy.props.BoolProperty(
        name="Crease Edges", default=False,
    )
    default_use_bevel: bpy.props.BoolProperty(
        name="Bevel Weight", default=False,
    )
    default_use_mesh_island: bpy.props.BoolProperty(
        name="Mesh Island", default=False,
    )
    default_normal_angle: bpy.props.FloatProperty(
        name="Angle",
        subtype='ANGLE',
        min=0.0,
        max=3.14159,
        default=0.5236,  # 30 degrees
    )

    def draw(self, context):
        layout = self.layout

        # -- Shortcuts -----------------------------------------------------
        box = layout.box()
        box.label(text="Shortcuts", icon='EVENT_OS')
        col = box.column()

        wm = context.window_manager
        kc = wm.keyconfigs.user
        km = kc.keymaps.get("3D View")
        if km:
            import rna_keymap_ui
            # Draw in a deliberate order.
            draw_order = (
                "paint_limit.toggle",
                "paint_limit.toggle_pin",
                "paint_limit.clear",
            )
            kmi_map = {}
            for kmi in km.keymap_items:
                if kmi.idname in draw_order and kmi.idname not in kmi_map:
                    kmi_map[kmi.idname] = kmi
            for op_id in draw_order:
                kmi = kmi_map.get(op_id)
                if kmi:
                    col.context_pointer_set("keymap", km)
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)

        # -- Startup Defaults ----------------------------------------------
        box = layout.box()
        box.label(text="Startup Defaults", icon='PREFERENCES')
        col = box.column()
        col.prop(self, "default_enabled")
        col.prop(self, "default_pin_mask")

        col.separator()
        col.label(text="Boundary Types:")
        col.prop(self, "default_use_single_face")
        col.prop(self, "default_use_sharp")
        col.prop(self, "default_use_uv_island")
        row = col.row(align=True)
        row.prop(self, "default_use_normal")
        sub = row.row(align=True)
        sub.active = self.default_use_normal
        sub.prop(self, "default_normal_angle")
        col.prop(self, "default_use_face_set")
        col.prop(self, "default_use_crease")
        col.prop(self, "default_use_bevel")
        col.prop(self, "default_use_mesh_island")


@bpy.app.handlers.persistent
def _apply_startup_defaults(_dummy):
    """Apply user-configured defaults when starting with a new file."""
    if bpy.data.filepath:
        return  # Opening a saved file — keep its settings.

    addon = bpy.context.preferences.addons.get(__package__)
    if addon is None:
        return
    p = addon.preferences

    for scene in bpy.data.scenes:
        s = scene.paint_area_limiters
        s.delimiter_enabled = p.default_enabled
        s.pin_mask_area = p.default_pin_mask
        s.use_single_face = p.default_use_single_face
        s.use_sharp = p.default_use_sharp
        s.use_uv_island = p.default_use_uv_island
        s.use_normal = p.default_use_normal
        s.use_face_set = p.default_use_face_set
        s.use_crease = p.default_use_crease
        s.use_bevel = p.default_use_bevel
        s.use_mesh_island = p.default_use_mesh_island
        s.normal_angle = p.default_normal_angle


_classes = (
    PaintAreaMaskItem,
    PaintAreaLimiterSettings,
    PaintAreaLimiterPreferences,
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
    VIEW3D_PT_boundary_delimiters,
    VIEW3D_PT_boundary_masks,
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

    # -- Shortcut keymaps (toggle/clear, shown in preferences) ---------------
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type='VIEW_3D')
        for op_id in ("paint_limit.toggle", "paint_limit.toggle_pin",
                      "paint_limit.clear"):
            kmi = km.keymap_items.new(op_id, 'NONE', 'PRESS')
            _shortcut_keymaps.append((km, kmi))

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
            # Ctrl+Shift+LMB — replace pinned mask with new region
            kmi = km.keymap_items.new(
                "paint_limit.auto_select", 'LEFTMOUSE', 'PRESS',
                ctrl=True, shift=True,
            )
            _addon_keymaps.append((km, kmi))

    # -- Tool header popover buttons --------------------------------------
    bpy.types.VIEW3D_HT_tool_header.append(draw_tool_header)

    # -- Load handler for startup defaults ---------------------------------
    bpy.app.handlers.load_post.append(_apply_startup_defaults)


def unregister():

    bpy.app.handlers.load_post.remove(_apply_startup_defaults)

    bpy.types.VIEW3D_HT_tool_header.remove(draw_tool_header)

    for km, kmi in _shortcut_keymaps:
        km.keymap_items.remove(kmi)
    _shortcut_keymaps.clear()

    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    del bpy.types.Object.paint_area_masks_active
    del bpy.types.Object.paint_area_masks
    del bpy.types.Scene.paint_area_limiters

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
