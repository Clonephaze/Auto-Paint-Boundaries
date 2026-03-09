# Auto Paint Boundaries — boundary-aware face masking for Blender.
# Copyright (C) 2026 Jack Smith/Clonephaze
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Panels for Auto Paint Boundaries.

``VIEW3D_PT_paint_area_limiters``
    Sub-panel inside *Brush Settings*, shown after the Cursor
    sub-panel in paint and sculpt modes.

``VIEW3D_PT_boundary_delimiters``
    Popover panel for the tool header — boundary type toggles.

``VIEW3D_PT_boundary_masks``
    Popover panel for the tool header — pin mask + saved masks.
"""

import bpy

from .delimiter import SUPPORTED_MODES, _has_topology_modifiers


class VIEW3D_PT_paint_area_limiters(bpy.types.Panel):
    """Auto boundary face-masking settings, nested inside Brush Settings."""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_label = "Auto Boundaries"
    bl_parent_id = "VIEW3D_PT_tools_brush_settings"
    bl_order = 100  # appear after all built-in sub-panels (Cursor, etc.)
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.mode in SUPPORTED_MODES

    def draw_header(self, context):
        settings = context.scene.paint_area_limiters
        self.layout.prop(settings, "delimiter_enabled", text="")

    def draw(self, context):
        settings = context.scene.paint_area_limiters
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.active = settings.delimiter_enabled

        # Warn when unapplied modifiers change the face count and pin
        # is off.  The deferred _clear_mask races with Blender's TBB
        # paint workers on the evaluated mesh copy, causing a crash.
        # With pin enabled, _schedule_clear never fires — no race.
        obj = context.active_object
        has_topo_mods = (
            obj is not None
            and obj.type == "MESH"
            and _has_topology_modifiers(context, obj)
        )

        col = layout.column()

        # -- Pin (behavioral modifier) — sits at the top ---------------
        box = col.box()
        row = box.row()
        row.prop(settings, "pin_mask_area",
                 icon='PINNED' if settings.pin_mask_area else 'UNPINNED')
        if settings.pin_mask_area:
            row.operator("paint_limit.clear", text="", icon='X')

        if has_topo_mods and not settings.pin_mask_area:
            box = col.box()
            box.alert = True
            box.label(text="Pin Mask Area required!", icon='ERROR')
            inner = box.column(align=True)
            inner.scale_y = 0.75
            inner.label(text="Modifiers that change face count")
            inner.label(text="(e.g. Subdivision Surface) require")
            inner.label(text="Pin Mask Area to be enabled, or")
            inner.label(text="apply the modifiers first.")
            inner.label(text="Pin will be auto-enabled on use.")
            return

        col.separator(factor=0.5)

        # -- Topology --------------------------------------------------
        col.label(text="Topology")
        sub = col.column(align=True)
        sub.prop(settings, "use_single_face", toggle=True,
                 icon='SNAP_FACE')
        sub.prop(settings, "use_mesh_island", toggle=True,
                 icon='OUTLINER_OB_MESH')
        sub.prop(settings, "use_face_set", toggle=True,
                 icon='FACE_MAPS')

        col.separator(factor=0.5)

        # -- Surface ---------------------------------------------------
        col.label(text="Surface")
        sub = col.column(align=True)
        sub.prop(settings, "use_normal", toggle=True,
                 icon='NORMALS_FACE')
        sub2 = col.column(align=True)
        sub2.use_property_split = True
        sub2.active = settings.use_normal
        sub2.prop(settings, "normal_angle")

        col.separator(factor=0.5)

        # -- Edge Attributes -------------------------------------------
        col.label(text="Edge Attributes")
        sub = col.column(align=True)
        row = sub.row(align=True)
        row.prop(settings, "use_sharp", toggle=True,
                 icon='MOD_EDGESPLIT')
        row.prop(settings, "use_uv_island", toggle=True,
                 icon='UV_ISLANDSEL')
        row = sub.row(align=True)
        row.prop(settings, "use_crease", toggle=True,
                 icon='LINCURVE')
        row.prop(settings, "use_bevel", toggle=True,
                 icon='MOD_BEVEL')


class VIEW3D_PT_paint_area_saved_masks(bpy.types.Panel):
    """Saved face-mask presets, nested under the Auto Boundaries panel."""

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_label = "Saved Masks"
    bl_parent_id = "VIEW3D_PT_paint_area_limiters"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if context.mode not in SUPPORTED_MODES:
            return False
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        obj = context.active_object

        row = layout.row()
        row.template_list(
            "PAINTLIMIT_UL_masks", "",
            obj, "paint_area_masks",
            obj, "paint_area_masks_active",
            rows=3,
        )

        side = row.column(align=True)
        side.operator("paint_limit.mask_save", text="", icon='ADD')
        side.operator("paint_limit.mask_remove", text="", icon='REMOVE')
        side.separator()
        side.operator("paint_limit.mask_overwrite", text="",
                      icon='FILE_REFRESH')

        # Load button below the list (only when a mask is selected)
        masks = obj.paint_area_masks
        idx = obj.paint_area_masks_active
        if 0 <= idx < len(masks):
            layout.operator("paint_limit.mask_load",
                            icon='CHECKMARK')


# ===================================================================
#  Tool-header popover: Boundary Delimiters
# ===================================================================


class VIEW3D_PT_boundary_delimiters(bpy.types.Panel):
    """Popover for boundary type settings in the tool header."""

    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Boundary Delimiters"

    def draw(self, context):
        settings = context.scene.paint_area_limiters
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        col = layout.column()

        # -- Topology --------------------------------------------------
        col.label(text="Topology")
        sub = col.column(align=True)
        sub.prop(settings, "use_single_face", toggle=True,
                 icon='SNAP_FACE')
        sub.prop(settings, "use_mesh_island", toggle=True,
                 icon='OUTLINER_OB_MESH')
        sub.prop(settings, "use_face_set", toggle=True,
                 icon='FACE_MAPS')

        col.separator(factor=0.5)

        # -- Surface ---------------------------------------------------
        col.label(text="Surface")
        sub = col.column(align=True)
        sub.prop(settings, "use_normal", toggle=True,
                 icon='NORMALS_FACE')
        sub2 = col.column(align=True)
        sub2.use_property_split = True
        sub2.active = settings.use_normal
        sub2.prop(settings, "normal_angle")

        col.separator(factor=0.5)

        # -- Edge Attributes -------------------------------------------
        col.label(text="Edge Attributes")
        sub = col.column(align=True)
        row = sub.row(align=True)
        row.prop(settings, "use_sharp", toggle=True,
                 icon='MOD_EDGESPLIT')
        row.prop(settings, "use_uv_island", toggle=True,
                 icon='UV_ISLANDSEL')
        row = sub.row(align=True)
        row.prop(settings, "use_crease", toggle=True,
                 icon='LINCURVE')
        row.prop(settings, "use_bevel", toggle=True,
                 icon='MOD_BEVEL')

        col.separator()

        # Hotkey tip
        box = col.box()
        inner = box.column(align=True)
        inner.scale_y = 0.75
        inner.label(text="Tip: Assign hotkeys in", icon='INFO')
        inner.label(text="Edit > Preferences > Keymap")


# ===================================================================
#  Tool-header popover: Pin Mask & Saved Masks
# ===================================================================


class VIEW3D_PT_boundary_masks(bpy.types.Panel):
    """Popover for pin mask area and saved masks in the tool header."""

    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Boundary Masks"

    def draw(self, context):
        settings = context.scene.paint_area_limiters
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        obj = context.active_object

        col = layout.column()

        # -- Pin -------------------------------------------------------
        box = col.box()
        row = box.row()
        row.prop(settings, "pin_mask_area",
                 icon='PINNED' if settings.pin_mask_area else 'UNPINNED')
        if settings.pin_mask_area:
            row.operator("paint_limit.clear", text="", icon='X')

        # Topology modifier warning
        if (obj is not None and obj.type == "MESH"
                and _has_topology_modifiers(context, obj)
                and not settings.pin_mask_area):
            box = col.box()
            box.alert = True
            box.label(text="Pin Mask Area required!", icon='ERROR')
            inner = box.column(align=True)
            inner.scale_y = 0.75
            inner.label(text="Modifiers that change face count")
            inner.label(text="require Pin Mask Area enabled,")
            inner.label(text="or apply the modifiers first.")
            inner.label(text="Pin will be auto-enabled on use.")

        col.separator(factor=0.5)

        # -- Saved Masks -----------------------------------------------
        if obj is not None and obj.type == "MESH":
            col.label(text="Saved Masks")

            row = col.row()
            row.template_list(
                "PAINTLIMIT_UL_masks", "",
                obj, "paint_area_masks",
                obj, "paint_area_masks_active",
                rows=3,
            )

            side = row.column(align=True)
            side.operator("paint_limit.mask_save", text="", icon='ADD')
            side.operator("paint_limit.mask_remove", text="", icon='REMOVE')
            side.separator()
            side.operator("paint_limit.mask_overwrite", text="",
                          icon='FILE_REFRESH')

            masks = obj.paint_area_masks
            idx = obj.paint_area_masks_active
            if 0 <= idx < len(masks):
                col.operator("paint_limit.mask_load", icon='CHECKMARK')


# ===================================================================
#  Tool-header draw callback
# ===================================================================


def draw_tool_header(self, context):
    """Appended to VIEW3D_HT_tool_header; adds two popover buttons
    with inline checkboxes in supported paint modes."""
    if context.mode not in SUPPORTED_MODES:
        return
    settings = getattr(context.scene, "paint_area_limiters", None)
    if settings is None:
        return

    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    row.prop(settings, "delimiter_enabled", text="")
    row.popover(
        panel="VIEW3D_PT_boundary_delimiters",
        text="Boundaries",
    )
    row = layout.row(align=True)
    row.active = settings.delimiter_enabled
    row.prop(settings, "pin_mask_area", text="")
    row.popover(
        panel="VIEW3D_PT_boundary_masks",
        text="Pin Masks",
    )
