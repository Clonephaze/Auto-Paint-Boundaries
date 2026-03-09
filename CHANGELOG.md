# Changelog

## 1.1.0

### Added
- **Tool header buttons** — Boundaries and Pin Masks controls appear directly in the tool header bar during paint modes, with inline checkboxes for quick toggling.
- **Addon preferences panel** — Configure custom keyboard shortcuts for Toggle Boundaries, Toggle Pin Mask, and Clear Selection. Set startup defaults for all settings (boundary types, pin mask, normal angle).
- **Startup defaults** — Preferred boundary settings are automatically applied when opening a new file.

### Changed
- **Removed D / Shift+D default keybinds** — These no longer override user keymaps. Toggle shortcuts can now be assigned in the addon preferences instead.
- **Mask clearing safety** — Timer-deferred clears only toggle `use_paint_mask` off; full polygon writes are reserved for user-initiated actions when no stroke is active.

## 1.0.0

- Initial release on Blender Extensions platform.
- Boundary-constrained face masking for Texture Paint, Vertex Paint, and Weight Paint.
- Boundary types: Single Face, Sharp Edges, UV Seams, Normal Angle, Face Set, Crease Edges, Bevel Weight, Mesh Island.
- Pin Mask Area with additive/subtractive region editing.
- Saved Masks: save, load, rename, and remove face selection presets per object.
- Symmetry mirroring support via KDTree.
- Side panel nested under brush settings.
