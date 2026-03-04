# Auto Paint Boundaries — boundary-aware face masking for Blender.
# Copyright (C) 2026 Jack Smith/Clonephaze
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Core algorithms for boundary-constrained face selection.

- **Face connectivity** — bmesh BFS with boundary-based edge detection
"""

from collections import deque

import bmesh


# ===================================================================
#  Face connectivity with boundary-based rules
# ===================================================================


def get_connected_face_indices(mesh_data, seed_face_index, delimiters,
                               normal_angle=0.5236):
    """Return the set of face indices reachable from *seed_face_index*.

    Uses ``bmesh`` BFS, stopping at edges that match *any* active
    boundary rule in the set.

    Args:
        mesh_data: ``bpy.types.Mesh``.
        seed_face_index: Index of the face the user clicked.
        delimiters: A set of boundary-rule strings, e.g. ``{"SHARP", "UV_ISLAND"}``.
            ``"FACE"`` returns only the seed face.
            ``"MESH_ISLAND"`` imposes no boundaries (ignored).
        normal_angle: Radian threshold for the ``'NORMAL'`` boundary.

    Returns:
        ``set[int]`` of polygon indices.
    """
    if "FACE" in delimiters:
        return {seed_face_index}

    # MESH_ISLAND imposes no boundary — remove it so the BFS is
    # unconstrained unless other boundary rules are also present.
    active = set(delimiters) - {"MESH_ISLAND"}

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh_data)
        bm.faces.ensure_lookup_table()

        seed = bm.faces[seed_face_index]
        visited = {seed.index}
        queue = deque([seed])

        # Pre-fetch face-set layer if needed.
        face_set_layer = None
        if "FACE_SET" in active:
            face_set_layer = (
                bm.faces.layers.int.get(".sculpt_face_set")
                or bm.faces.layers.int.get("face_set")
                or bm.faces.layers.int.get(".face_set")
            )
            if face_set_layer is None:
                active.discard("FACE_SET")

        seed_set_val = None
        if face_set_layer is not None:
            seed_set_val = seed[face_set_layer]

        # Pre-fetch crease layer if needed.
        crease_layer = None
        if "CREASE" in active:
            crease_layer = (
                bm.edges.layers.float.get("crease_edge")
                or bm.edges.layers.float.get("crease")
            )
            if crease_layer is None:
                active.discard("CREASE")

        # Pre-fetch bevel weight layer if needed.
        bevel_layer = None
        if "BEVEL" in active:
            bevel_layer = (
                bm.edges.layers.float.get("bevel_weight_edge")
                or bm.edges.layers.float.get("bevel_weight")
            )
            if bevel_layer is None:
                active.discard("BEVEL")

        while queue:
            face = queue.popleft()
            for edge in face.edges:
                # Edge-level checks — any matching delimiter blocks traversal.
                blocked = False
                if "SHARP" in active and not edge.smooth:
                    blocked = True
                if not blocked and "UV_ISLAND" in active and edge.seam:
                    blocked = True
                if not blocked and "CREASE" in active and crease_layer is not None:
                    if edge[crease_layer] > 0.0:
                        blocked = True
                if not blocked and "BEVEL" in active and bevel_layer is not None:
                    if edge[bevel_layer] > 0.0:
                        blocked = True

                if blocked:
                    continue

                for linked_face in edge.link_faces:
                    if linked_face.index in visited:
                        continue
                    # Face-level checks.
                    if "NORMAL" in active:
                        if face.normal.angle(linked_face.normal) > normal_angle:
                            continue
                    if "FACE_SET" in active and face_set_layer is not None:
                        if linked_face[face_set_layer] != seed_set_val:
                            continue

                    visited.add(linked_face.index)
                    queue.append(linked_face)
    finally:
        bm.free()

    return visited


# ===================================================================
#  Symmetry helpers
# ===================================================================


def find_mirror_seeds(mesh_data, seed_index, mirror_x, mirror_y, mirror_z):
    """Return face indices that mirror *seed_index* across active axes.

    Uses a KDTree of face centres.  For multiple active axes the
    diagonal mirrors (e.g. X + Y) are also included.
    """
    from itertools import combinations
    from mathutils import kdtree as kdt

    n = len(mesh_data.polygons)
    if n == 0:
        return set()

    kd = kdt.KDTree(n)
    for poly in mesh_data.polygons:
        kd.insert(poly.center, poly.index)
    kd.balance()

    center = mesh_data.polygons[seed_index].center

    axes = []
    if mirror_x:
        axes.append(0)
    if mirror_y:
        axes.append(1)
    if mirror_z:
        axes.append(2)

    mirrors = set()
    for r in range(1, len(axes) + 1):
        for combo in combinations(axes, r):
            mc = center.copy()
            for axis in combo:
                mc[axis] = -mc[axis]
            _, idx, dist = kd.find(mc)
            if idx is not None and dist < 0.001 and idx != seed_index:
                mirrors.add(idx)

    return mirrors
