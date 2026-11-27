"""Clean-room Live2D Cubism .moc3 binary writer (versions 3 and 4).

Follows the exact binary layout documented in Mochi2D (docs/moc-data.md,
src/core/moc/schema.ts, src/core/moc/io.ts):
  - 64-byte header ("MOC3", version, endianness=0)
  - 480-slot uint32 offset table
  - 64-byte aligned 32-entry int32 count table (slot 0)
  - 64-byte aligned 64-byte canvas block (slot 1)
  - All version fields in ascending slot order, 64-byte aligned
    (with non-empty name arrays packed directly after their preceding placeholder)
  - File padded to a multiple of 64 bytes
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

HEADER_SIZE = 0x40
SLOT_COUNT_V3_V4 = 480
COUNT_TABLE_LEN_V3_V4 = 32
COUNT_TABLE_SLOT = 0
CANVAS_SLOT = 1
CANVAS_BLOCK_SIZE = 64

# Count table indices
C_PARTS = 0
C_DEFORMERS = 1
C_WARPS = 2
C_ROTATIONS = 3
C_ART_MESHES = 4
C_PARAMETERS = 5
C_PART_KEYFORMS = 6
C_WARP_KEYFORMS = 7
C_ROTATION_KEYFORMS = 8
C_ART_MESH_KEYFORMS = 9
C_POSITION_FLOATS = 10
C_BINDING_INDEX_ENTRIES = 11
C_BANDS = 12
C_PARAMETER_BINDINGS = 13
C_KEY_VALUES = 14
C_UV_FLOATS = 15
C_TRIANGLE_INDICES = 16
C_MASK_ENTRIES = 17
C_DRAW_ORDER_GROUPS = 18
C_DRAW_ORDER_GROUP_OBJECTS = 19
C_GLUES = 20
C_GLUE_INFO = 21
C_GLUE_KEYFORMS = 22
# v4+
C_MULTIPLY_COLORS = 23
C_SCREEN_COLORS = 24
C_BS_PARAM_BINDINGS = 25
C_BS_KEYFORM_BINDINGS = 26
C_WARP_BS_TARGETS = 27
C_MESH_BS_TARGETS = 28
C_BS_CONSTRAINT_INDICES = 29
C_BS_CONSTRAINTS = 30
C_BS_CONSTRAINT_VALUES = 31

ELEMENT_SIZE = {
    "name": 64,
    "placeholder": 8,
    "i32": 4,
    "f32": 4,
    "u16": 2,
    "u8": 1,
}

# (key, slot, type, count_idx, since_version)
FIELD_TABLE: list[tuple[str, int, str, int, int]] = [
    # Parts
    ("part.reserved", 2, "placeholder", C_PARTS, 1),
    ("part.id", 3, "name", C_PARTS, 1),
    ("part.band", 4, "i32", C_PARTS, 1),
    ("part.firstKeyform", 5, "i32", C_PARTS, 1),
    ("part.keyformCount", 6, "i32", C_PARTS, 1),
    ("part.initiallyVisible", 7, "i32", C_PARTS, 1),
    ("part.enabled", 8, "i32", C_PARTS, 1),
    ("part.parent", 9, "i32", C_PARTS, 1),
    # Deformers
    ("deformer.reserved", 10, "placeholder", C_DEFORMERS, 1),
    ("deformer.id", 11, "name", C_DEFORMERS, 1),
    ("deformer.band", 12, "i32", C_DEFORMERS, 1),
    ("deformer.visible", 13, "i32", C_DEFORMERS, 1),
    ("deformer.enabled", 14, "i32", C_DEFORMERS, 1),
    ("deformer.part", 15, "i32", C_DEFORMERS, 1),
    ("deformer.parent", 16, "i32", C_DEFORMERS, 1),
    ("deformer.kind", 17, "i32", C_DEFORMERS, 1),
    ("deformer.kindIndex", 18, "i32", C_DEFORMERS, 1),
    # Warp deformers
    ("warp.band", 19, "i32", C_WARPS, 1),
    ("warp.firstKeyform", 20, "i32", C_WARPS, 1),
    ("warp.keyformCount", 21, "i32", C_WARPS, 1),
    ("warp.pointCount", 22, "i32", C_WARPS, 1),
    ("warp.rows", 23, "i32", C_WARPS, 1),
    ("warp.columns", 24, "i32", C_WARPS, 1),
    ("warp.bilinear", 101, "i32", C_WARPS, 2),
    ("warp.firstColor", 105, "i32", C_WARPS, 4),
    # Rotation deformers
    ("rotation.band", 25, "i32", C_ROTATIONS, 1),
    ("rotation.firstKeyform", 26, "i32", C_ROTATIONS, 1),
    ("rotation.keyformCount", 27, "i32", C_ROTATIONS, 1),
    ("rotation.baseAngle", 28, "f32", C_ROTATIONS, 1),
    ("rotation.firstColor", 106, "i32", C_ROTATIONS, 4),
    # Art meshes
    ("mesh.reserved0", 29, "placeholder", C_ART_MESHES, 1),
    ("mesh.reserved1", 30, "placeholder", C_ART_MESHES, 1),
    ("mesh.reserved2", 31, "placeholder", C_ART_MESHES, 1),
    ("mesh.reserved3", 32, "placeholder", C_ART_MESHES, 1),
    ("mesh.id", 33, "name", C_ART_MESHES, 1),
    ("mesh.band", 34, "i32", C_ART_MESHES, 1),
    ("mesh.firstKeyform", 35, "i32", C_ART_MESHES, 1),
    ("mesh.keyformCount", 36, "i32", C_ART_MESHES, 1),
    ("mesh.visible", 37, "i32", C_ART_MESHES, 1),
    ("mesh.enabled", 38, "i32", C_ART_MESHES, 1),
    ("mesh.part", 39, "i32", C_ART_MESHES, 1),
    ("mesh.deformer", 40, "i32", C_ART_MESHES, 1),
    ("mesh.texture", 41, "i32", C_ART_MESHES, 1),
    ("mesh.flags", 42, "u8", C_ART_MESHES, 1),
    ("mesh.vertexCount", 43, "i32", C_ART_MESHES, 1),
    ("mesh.firstUv", 44, "i32", C_ART_MESHES, 1),
    ("mesh.firstTriangleIndex", 45, "i32", C_ART_MESHES, 1),
    ("mesh.triangleIndexCount", 46, "i32", C_ART_MESHES, 1),
    ("mesh.firstMask", 47, "i32", C_ART_MESHES, 1),
    ("mesh.maskCount", 48, "i32", C_ART_MESHES, 1),
    ("mesh.firstColor", 107, "i32", C_ART_MESHES, 4),
    # Parameters
    ("parameter.reserved", 49, "placeholder", C_PARAMETERS, 1),
    ("parameter.id", 50, "name", C_PARAMETERS, 1),
    ("parameter.max", 51, "f32", C_PARAMETERS, 1),
    ("parameter.min", 52, "f32", C_PARAMETERS, 1),
    ("parameter.default", 53, "f32", C_PARAMETERS, 1),
    ("parameter.repeat", 54, "i32", C_PARAMETERS, 1),
    ("parameter.decimals", 55, "i32", C_PARAMETERS, 1),
    ("parameter.firstBinding", 56, "i32", C_PARAMETERS, 1),
    ("parameter.bindingCount", 57, "i32", C_PARAMETERS, 1),
    ("parameter.reserved4", 102, "placeholder", C_PARAMETERS, 4),
    ("parameter.firstKey", 103, "i32", C_PARAMETERS, 4),
    ("parameter.keyCount", 104, "i32", C_PARAMETERS, 4),
    ("parameter.type", 114, "i32", C_PARAMETERS, 4),
    ("parameter.firstBlendShapeBinding", 115, "i32", C_PARAMETERS, 4),
    ("parameter.blendShapeBindingCount", 116, "i32", C_PARAMETERS, 4),
    # Keyforms
    ("partKeyform.drawOrder", 58, "f32", C_PART_KEYFORMS, 1),
    ("warpKeyform.opacity", 59, "f32", C_WARP_KEYFORMS, 1),
    ("warpKeyform.firstPosition", 60, "i32", C_WARP_KEYFORMS, 1),
    ("rotationKeyform.opacity", 61, "f32", C_ROTATION_KEYFORMS, 1),
    ("rotationKeyform.angle", 62, "f32", C_ROTATION_KEYFORMS, 1),
    ("rotationKeyform.originX", 63, "f32", C_ROTATION_KEYFORMS, 1),
    ("rotationKeyform.originY", 64, "f32", C_ROTATION_KEYFORMS, 1),
    ("rotationKeyform.scale", 65, "f32", C_ROTATION_KEYFORMS, 1),
    ("rotationKeyform.mirrorX", 66, "i32", C_ROTATION_KEYFORMS, 1),
    ("rotationKeyform.mirrorY", 67, "i32", C_ROTATION_KEYFORMS, 1),
    ("meshKeyform.opacity", 68, "f32", C_ART_MESH_KEYFORMS, 1),
    ("meshKeyform.drawOrder", 69, "f32", C_ART_MESH_KEYFORMS, 1),
    ("meshKeyform.firstPosition", 70, "i32", C_ART_MESH_KEYFORMS, 1),
    ("glueKeyform.intensity", 100, "f32", C_GLUE_KEYFORMS, 1),
    # Shared pools & bindings
    ("positions", 71, "f32", C_POSITION_FLOATS, 1),
    ("bindingIndex", 72, "i32", C_BINDING_INDEX_ENTRIES, 1),
    ("band.firstEntry", 73, "i32", C_BANDS, 1),
    ("band.entryCount", 74, "i32", C_BANDS, 1),
    ("binding.firstKey", 75, "i32", C_PARAMETER_BINDINGS, 1),
    ("binding.keyCount", 76, "i32", C_PARAMETER_BINDINGS, 1),
    ("keys", 77, "f32", C_KEY_VALUES, 1),
    ("uvs", 78, "f32", C_UV_FLOATS, 1),
    ("triangleIndices", 79, "u16", C_TRIANGLE_INDICES, 1),
    ("maskEntries", 80, "i32", C_MASK_ENTRIES, 1),
    # Draw-order groups
    ("group.firstObject", 81, "i32", C_DRAW_ORDER_GROUPS, 1),
    ("group.objectCount", 82, "i32", C_DRAW_ORDER_GROUPS, 1),
    ("group.entryCount", 83, "i32", C_DRAW_ORDER_GROUPS, 1),
    ("group.maxDrawOrder", 84, "i32", C_DRAW_ORDER_GROUPS, 1),
    ("group.minDrawOrder", 85, "i32", C_DRAW_ORDER_GROUPS, 1),
    ("groupObject.kind", 86, "i32", C_DRAW_ORDER_GROUP_OBJECTS, 1),
    ("groupObject.index", 87, "i32", C_DRAW_ORDER_GROUP_OBJECTS, 1),
    ("groupObject.nestedGroup", 88, "i32", C_DRAW_ORDER_GROUP_OBJECTS, 1),
    # Glues
    ("glue.reserved", 89, "placeholder", C_GLUES, 1),
    ("glue.id", 90, "name", C_GLUES, 1),
    ("glue.band", 91, "i32", C_GLUES, 1),
    ("glue.firstKeyform", 92, "i32", C_GLUES, 1),
    ("glue.keyformCount", 93, "i32", C_GLUES, 1),
    ("glue.meshA", 94, "i32", C_GLUES, 1),
    ("glue.meshB", 95, "i32", C_GLUES, 1),
    ("glue.firstInfo", 96, "i32", C_GLUES, 1),
    ("glue.infoCount", 97, "i32", C_GLUES, 1),
    ("glueInfo.weight", 98, "f32", C_GLUE_INFO, 1),
    ("glueInfo.vertex", 99, "u16", C_GLUE_INFO, 1),
    # v4 colors & blend shapes
    ("multiplyColor.r", 108, "f32", C_MULTIPLY_COLORS, 4),
    ("multiplyColor.g", 109, "f32", C_MULTIPLY_COLORS, 4),
    ("multiplyColor.b", 110, "f32", C_MULTIPLY_COLORS, 4),
    ("screenColor.r", 111, "f32", C_SCREEN_COLORS, 4),
    ("screenColor.g", 112, "f32", C_SCREEN_COLORS, 4),
    ("screenColor.b", 113, "f32", C_SCREEN_COLORS, 4),
    ("bsBinding.firstKey", 117, "i32", C_BS_PARAM_BINDINGS, 4),
    ("bsBinding.keyCount", 118, "i32", C_BS_PARAM_BINDINGS, 4),
    ("bsBinding.baseKey", 119, "i32", C_BS_PARAM_BINDINGS, 4),
    ("bsKeyformBinding.binding", 120, "i32", C_BS_KEYFORM_BINDINGS, 4),
    ("bsKeyformBinding.firstKeyform", 121, "i32", C_BS_KEYFORM_BINDINGS, 4),
    ("bsKeyformBinding.keyformCount", 122, "i32", C_BS_KEYFORM_BINDINGS, 4),
    ("bsKeyformBinding.firstConstraintEntry", 123, "i32", C_BS_KEYFORM_BINDINGS, 4),
    ("bsKeyformBinding.constraintEntryCount", 124, "i32", C_BS_KEYFORM_BINDINGS, 4),
    ("warpTarget.warp", 125, "i32", C_WARP_BS_TARGETS, 4),
    ("warpTarget.firstBinding", 126, "i32", C_WARP_BS_TARGETS, 4),
    ("warpTarget.bindingCount", 127, "i32", C_WARP_BS_TARGETS, 4),
    ("meshTarget.mesh", 128, "i32", C_MESH_BS_TARGETS, 4),
    ("meshTarget.firstBinding", 129, "i32", C_MESH_BS_TARGETS, 4),
    ("meshTarget.bindingCount", 130, "i32", C_MESH_BS_TARGETS, 4),
    ("constraintIndex", 131, "i32", C_BS_CONSTRAINT_INDICES, 4),
    ("constraint.parameter", 132, "i32", C_BS_CONSTRAINTS, 4),
    ("constraint.firstValue", 133, "i32", C_BS_CONSTRAINTS, 4),
    ("constraint.valueCount", 134, "i32", C_BS_CONSTRAINTS, 4),
    ("constraintValue.key", 135, "f32", C_BS_CONSTRAINT_VALUES, 4),
    ("constraintValue.weight", 136, "f32", C_BS_CONSTRAINT_VALUES, 4),
]


def _f32(v: float) -> float:
    return float(np.float32(v))


def _align64(n: int) -> int:
    return (n + 63) & ~63


@dataclass
class ParamSpec:
    id: str
    min_val: float
    default_val: float
    max_val: float
    repeat: int = 0
    decimals: int = 3
    # key_tuple -> local binding id (resolved at build time)
    bindings: list[tuple[float, ...]] = field(default_factory=list)


@dataclass
class PartSpec:
    id: str
    parent: int = -1
    initially_visible: int = 1
    enabled: int = 1
    draw_order: float = 500.0


@dataclass
class WarpSpec:
    id: str
    parent: int
    part: int
    rows: int
    cols: int
    bilinear: int
    # List of (param_id, key_values_tuple) in innermost-first order!
    axes: list[tuple[str, tuple[float, ...]]]
    # Each keyform: (opacity, positions_flat_float32_array)
    keyforms: list[tuple[float, np.ndarray]]


@dataclass
class RotationSpec:
    id: str
    parent: int
    part: int
    base_angle: float
    axes: list[tuple[str, tuple[float, ...]]]
    # Each keyform: (opacity, angle, origin_x, origin_y, scale, mirror_x, mirror_y)
    keyforms: list[tuple[float, float, float, float, float, int, int]]


@dataclass
class ArtMeshSpec:
    id: str
    part: int
    deformer: int
    texture: int
    flags: int
    uvs: np.ndarray  # float32 shape (2*V,)
    triangles: np.ndarray  # uint16 shape (3*T,)
    masks: list[int]
    axes: list[tuple[str, tuple[float, ...]]]
    # Each keyform: (opacity, draw_order, positions_flat_float32_array)
    keyforms: list[tuple[float, float, np.ndarray]]


class Moc3Builder:
    """High-level builder for Live2D Cubism .moc3 files (version 3)."""

    def __init__(
        self,
        pixels_per_unit: float,
        origin_x: float,
        origin_y: float,
        width: float,
        height: float,
        flags: int = 0,
    ) -> None:
        self.ppu = _f32(pixels_per_unit)
        self.origin_x = _f32(origin_x)
        self.origin_y = _f32(origin_y)
        self.width = _f32(width)
        self.height = _f32(height)
        self.canvas_flags = int(flags)

        self.params: list[ParamSpec] = []
        self._param_by_id: dict[str, int] = {}
        self.parts: list[PartSpec] = []
        self._part_by_id: dict[str, int] = {}
        self.deformers: list[tuple[int, int]] = []  # (kind: 0=warp 1=rot, kind_idx)
        self.warps: list[WarpSpec] = []
        self.rotations: list[RotationSpec] = []
        self.meshes: list[ArtMeshSpec] = []
        self._mesh_by_id: dict[str, int] = {}

    def add_parameter(
        self,
        param_id: str,
        min_val: float,
        default_val: float,
        max_val: float,
        repeat: int = 0,
        decimals: int = 3,
    ) -> int:
        if param_id in self._param_by_id:
            return self._param_by_id[param_id]
        idx = len(self.params)
        self.params.append(
            ParamSpec(
                id=param_id,
                min_val=_f32(min_val),
                default_val=_f32(default_val),
                max_val=_f32(max_val),
                repeat=int(repeat),
                decimals=int(decimals),
            )
        )
        self._param_by_id[param_id] = idx
        return idx

    def add_part(self, part_id: str, parent: int = -1, initially_visible: int = 1) -> int:
        if part_id in self._part_by_id:
            return self._part_by_id[part_id]
        idx = len(self.parts)
        self.parts.append(PartSpec(id=part_id, parent=parent, initially_visible=initially_visible))
        self._part_by_id[part_id] = idx
        return idx

    def add_warp_deformer(
        self,
        deformer_id: str,
        parent: int,
        part: int,
        rows: int,
        cols: int,
        axes: Sequence[tuple[str, Sequence[float]]],
        keyforms: Sequence[tuple[float, np.ndarray]],
        bilinear: int = 1,
    ) -> int:
        norm_axes = [(pid, tuple(_f32(k) for k in ks)) for pid, ks in axes]
        expected_kf = 1
        for _, ks in norm_axes:
            expected_kf *= len(ks)
        if len(keyforms) != expected_kf:
            raise ValueError(
                f"Warp {deformer_id}: expected {expected_kf} keyforms, got {len(keyforms)}"
            )
        npts = (rows + 1) * (cols + 1)
        norm_kfs = []
        for op, pos in keyforms:
            arr = np.asarray(pos, dtype=np.float32).reshape(-1)
            if arr.size != 2 * npts:
                raise ValueError(
                    f"Warp {deformer_id}: expected {2 * npts} floats, got {arr.size}"
                )
            norm_kfs.append((_f32(op), arr))
        w_idx = len(self.warps)
        self.warps.append(
            WarpSpec(
                id=deformer_id,
                parent=parent,
                part=part,
                rows=rows,
                cols=cols,
                bilinear=bilinear,
                axes=norm_axes,
                keyforms=norm_kfs,
            )
        )
        d_idx = len(self.deformers)
        self.deformers.append((0, w_idx))
        return d_idx

    def add_rotation_deformer(
        self,
        deformer_id: str,
        parent: int,
        part: int,
        axes: Sequence[tuple[str, Sequence[float]]],
        keyforms: Sequence[tuple[float, float, float, float, float, int, int]],
        base_angle: float = 0.0,
    ) -> int:
        norm_axes = [(pid, tuple(_f32(k) for k in ks)) for pid, ks in axes]
        expected_kf = 1
        for _, ks in norm_axes:
            expected_kf *= len(ks)
        if len(keyforms) != expected_kf:
            raise ValueError(
                f"Rotation {deformer_id}: expected {expected_kf} keyforms, got {len(keyforms)}"
            )
        norm_kfs = [
            (_f32(op), _f32(ang), _f32(ox), _f32(oy), _f32(sc), int(mx), int(my))
            for op, ang, ox, oy, sc, mx, my in keyforms
        ]
        r_idx = len(self.rotations)
        self.rotations.append(
            RotationSpec(
                id=deformer_id,
                parent=parent,
                part=part,
                base_angle=_f32(base_angle),
                axes=norm_axes,
                keyforms=norm_kfs,
            )
        )
        d_idx = len(self.deformers)
        self.deformers.append((1, r_idx))
        return d_idx

    def add_art_mesh(
        self,
        mesh_id: str,
        part: int,
        deformer: int,
        texture: int,
        flags: int,
        uvs: np.ndarray,
        triangles: np.ndarray,
        axes: Sequence[tuple[str, Sequence[float]]],
        keyforms: Sequence[tuple[float, float, np.ndarray]],
        masks: Sequence[int] = (),
    ) -> int:
        norm_axes = [(pid, tuple(_f32(k) for k in ks)) for pid, ks in axes]
        expected_kf = 1
        for _, ks in norm_axes:
            expected_kf *= len(ks)
        if len(keyforms) != expected_kf:
            raise ValueError(
                f"ArtMesh {mesh_id}: expected {expected_kf} keyforms, got {len(keyforms)}"
            )
        uv_arr = np.asarray(uvs, dtype=np.float32).reshape(-1)
        tri_arr = np.asarray(triangles, dtype=np.uint16).reshape(-1)
        vcount = uv_arr.size // 2
        if uv_arr.size != 2 * vcount:
            raise ValueError(f"ArtMesh {mesh_id}: odd UV count")
        norm_kfs = []
        for op, do, pos in keyforms:
            arr = np.asarray(pos, dtype=np.float32).reshape(-1)
            if arr.size != 2 * vcount:
                raise ValueError(
                    f"ArtMesh {mesh_id}: expected {2 * vcount} position floats, got {arr.size}"
                )
            norm_kfs.append((_f32(op), _f32(do), arr))
        m_idx = len(self.meshes)
        self.meshes.append(
            ArtMeshSpec(
                id=mesh_id,
                part=part,
                deformer=deformer,
                texture=int(texture),
                flags=int(flags),
                uvs=uv_arr,
                triangles=tri_arr,
                masks=[int(m) for m in masks],
                axes=norm_axes,
                keyforms=norm_kfs,
            )
        )
        self._mesh_by_id[mesh_id] = m_idx
        return m_idx

    def set_mesh_masks(self, mesh_idx: int, mask_indices: Sequence[int]) -> None:
        self.meshes[mesh_idx].masks = [int(m) for m in mask_indices]

    def build(self, version: int = 3) -> bytes:
        if version not in (3, 4):
            raise ValueError(f"Unsupported moc3 version {version} (use 3 or 4)")

        # 1. Collect unique (param_idx, keys_tuple) bindings per parameter
        param_binding_sets: list[list[tuple[float, ...]]] = [[] for _ in self.params]
        param_binding_map: dict[tuple[int, tuple[float, ...]], int] = {}

        def register_axis(pid: str, ks: tuple[float, ...]) -> tuple[int, tuple[float, ...]]:
            if pid not in self._param_by_id:
                raise KeyError(f"Unknown parameter id: {pid}")
            pidx = self._param_by_id[pid]
            if ks not in param_binding_sets[pidx]:
                param_binding_sets[pidx].append(ks)
            return pidx, ks

        for w in self.warps:
            for pid, ks in w.axes:
                register_axis(pid, ks)
        for r in self.rotations:
            for pid, ks in r.axes:
                register_axis(pid, ks)
        for m in self.meshes:
            for pid, ks in m.axes:
                register_axis(pid, ks)

        # Build flat parameterBindings & keys arrays (grouped by owning parameter)
        param_first_binding = np.zeros(len(self.params), dtype=np.int32)
        param_binding_count = np.zeros(len(self.params), dtype=np.int32)
        binding_first_key: list[int] = []
        binding_key_count: list[int] = []
        keys_pool: list[float] = []

        for pidx, bsets in enumerate(param_binding_sets):
            param_first_binding[pidx] = len(binding_first_key)
            param_binding_count[pidx] = len(bsets)
            for ks in bsets:
                b_idx = len(binding_first_key)
                param_binding_map[(pidx, ks)] = b_idx
                binding_first_key.append(len(keys_pool))
                binding_key_count.append(len(ks))
                keys_pool.extend(ks)

        # v4 parameter own key lists
        param_first_key = np.zeros(len(self.params), dtype=np.int32)
        param_key_count = np.zeros(len(self.params), dtype=np.int32)
        if version >= 4:
            for pidx, bsets in enumerate(param_binding_sets):
                uniq = sorted({k for ks in bsets for k in ks})
                param_first_key[pidx] = len(keys_pool)
                param_key_count[pidx] = len(uniq)
                keys_pool.extend(uniq)

        # 2. Build bands (deduplicated tuples of binding indices)
        band_first_entry: list[int] = []
        band_entry_count: list[int] = []
        binding_indices_pool: list[int] = []
        band_map: dict[tuple[int, ...], int] = {}

        def get_band(axes: Sequence[tuple[str, tuple[float, ...]]]) -> int:
            b_tuple = tuple(param_binding_map[(self._param_by_id[pid], ks)] for pid, ks in axes)
            if b_tuple in band_map:
                return band_map[b_tuple]
            band_idx = len(band_first_entry)
            band_first_entry.append(len(binding_indices_pool))
            band_entry_count.append(len(b_tuple))
            binding_indices_pool.extend(b_tuple)
            band_map[b_tuple] = band_idx
            return band_idx

        empty_band = get_band(())

        # 3. Parts
        n_parts = len(self.parts)
        part_ids = [p.id for p in self.parts]
        part_band = np.full(n_parts, empty_band, dtype=np.int32)
        part_first_kf = np.arange(n_parts, dtype=np.int32)
        part_kf_count = np.ones(n_parts, dtype=np.int32)
        part_init_vis = np.array([p.initially_visible for p in self.parts], dtype=np.int32)
        part_enabled = np.array([p.enabled for p in self.parts], dtype=np.int32)
        part_parent = np.array([p.parent for p in self.parts], dtype=np.int32)
        part_kf_draw_order = np.array([p.draw_order for p in self.parts], dtype=np.float32)

        # 4. Deformers, Warps, Rotations, ArtMeshes + shared pools
        positions_chunks: list[np.ndarray] = []
        positions_cursor = 0

        def push_positions(arr: np.ndarray) -> int:
            nonlocal positions_cursor
            start = positions_cursor
            positions_chunks.append(arr)
            positions_cursor += arr.size
            return start

        # Warps
        n_warps = len(self.warps)
        warp_band = np.zeros(n_warps, dtype=np.int32)
        warp_first_kf = np.zeros(n_warps, dtype=np.int32)
        warp_kf_count = np.zeros(n_warps, dtype=np.int32)
        warp_point_count = np.zeros(n_warps, dtype=np.int32)
        warp_rows = np.zeros(n_warps, dtype=np.int32)
        warp_cols = np.zeros(n_warps, dtype=np.int32)
        warp_bilinear = np.zeros(n_warps, dtype=np.int32)
        warp_first_color = np.zeros(n_warps, dtype=np.int32)
        warp_kf_opacity: list[float] = []
        warp_kf_first_pos: list[int] = []

        color_count = 0

        for wi, w in enumerate(self.warps):
            warp_band[wi] = get_band(w.axes)
            warp_first_kf[wi] = len(warp_kf_opacity)
            warp_kf_count[wi] = len(w.keyforms)
            warp_point_count[wi] = (w.rows + 1) * (w.cols + 1)
            warp_rows[wi] = w.rows
            warp_cols[wi] = w.cols
            warp_bilinear[wi] = w.bilinear
            warp_first_color[wi] = color_count
            color_count += len(w.keyforms)
            for op, pos in w.keyforms:
                warp_kf_opacity.append(op)
                warp_kf_first_pos.append(push_positions(pos))

        # Rotations
        n_rots = len(self.rotations)
        rot_band = np.zeros(n_rots, dtype=np.int32)
        rot_first_kf = np.zeros(n_rots, dtype=np.int32)
        rot_kf_count = np.zeros(n_rots, dtype=np.int32)
        rot_base_angle = np.zeros(n_rots, dtype=np.float32)
        rot_first_color = np.zeros(n_rots, dtype=np.int32)
        rot_kf_opacity: list[float] = []
        rot_kf_angle: list[float] = []
        rot_kf_ox: list[float] = []
        rot_kf_oy: list[float] = []
        rot_kf_scale: list[float] = []
        rot_kf_mx: list[int] = []
        rot_kf_my: list[int] = []

        for ri, r in enumerate(self.rotations):
            rot_band[ri] = get_band(r.axes)
            rot_first_kf[ri] = len(rot_kf_opacity)
            rot_kf_count[ri] = len(r.keyforms)
            rot_base_angle[ri] = r.base_angle
            rot_first_color[ri] = color_count
            color_count += len(r.keyforms)
            for op, ang, ox, oy, sc, mx, my in r.keyforms:
                rot_kf_opacity.append(op)
                rot_kf_angle.append(ang)
                rot_kf_ox.append(ox)
                rot_kf_oy.append(oy)
                rot_kf_scale.append(sc)
                rot_kf_mx.append(mx)
                rot_kf_my.append(my)

        # Deformers table
        n_defs = len(self.deformers)
        def_ids: list[str] = []
        def_band = np.zeros(n_defs, dtype=np.int32)
        def_visible = np.ones(n_defs, dtype=np.int32)
        def_enabled = np.ones(n_defs, dtype=np.int32)
        def_part = np.zeros(n_defs, dtype=np.int32)
        def_parent = np.zeros(n_defs, dtype=np.int32)
        def_kind = np.zeros(n_defs, dtype=np.int32)
        def_kind_idx = np.zeros(n_defs, dtype=np.int32)

        for di, (kind, kidx) in enumerate(self.deformers):
            def_kind[di] = kind
            def_kind_idx[di] = kidx
            if kind == 0:
                w = self.warps[kidx]
                def_ids.append(w.id)
                def_band[di] = warp_band[kidx]
                def_part[di] = w.part
                def_parent[di] = w.parent
            else:
                r = self.rotations[kidx]
                def_ids.append(r.id)
                def_band[di] = rot_band[kidx]
                def_part[di] = r.part
                def_parent[di] = r.parent

        # ArtMeshes
        n_meshes = len(self.meshes)
        mesh_ids: list[str] = []
        mesh_band = np.zeros(n_meshes, dtype=np.int32)
        mesh_first_kf = np.zeros(n_meshes, dtype=np.int32)
        mesh_kf_count = np.zeros(n_meshes, dtype=np.int32)
        mesh_visible = np.ones(n_meshes, dtype=np.int32)
        mesh_enabled = np.ones(n_meshes, dtype=np.int32)
        mesh_part = np.zeros(n_meshes, dtype=np.int32)
        mesh_deformer = np.zeros(n_meshes, dtype=np.int32)
        mesh_texture = np.zeros(n_meshes, dtype=np.int32)
        mesh_flags = np.zeros(n_meshes, dtype=np.uint8)
        mesh_vertex_count = np.zeros(n_meshes, dtype=np.int32)
        mesh_first_uv = np.zeros(n_meshes, dtype=np.int32)
        mesh_first_tri = np.zeros(n_meshes, dtype=np.int32)
        mesh_tri_count = np.zeros(n_meshes, dtype=np.int32)
        mesh_first_mask = np.zeros(n_meshes, dtype=np.int32)
        mesh_mask_count = np.zeros(n_meshes, dtype=np.int32)
        mesh_first_color = np.zeros(n_meshes, dtype=np.int32)

        mesh_kf_opacity: list[float] = []
        mesh_kf_draw_order: list[float] = []
        mesh_kf_first_pos: list[int] = []
        uv_chunks: list[np.ndarray] = []
        uv_cursor = 0
        tri_chunks: list[np.ndarray] = []
        tri_cursor = 0
        mask_entries: list[int] = []

        min_do = 1000
        max_do = 0

        for mi, m in enumerate(self.meshes):
            mesh_ids.append(m.id)
            mesh_band[mi] = get_band(m.axes)
            mesh_first_kf[mi] = len(mesh_kf_opacity)
            mesh_kf_count[mi] = len(m.keyforms)
            mesh_part[mi] = m.part
            mesh_deformer[mi] = m.deformer
            mesh_texture[mi] = m.texture
            mesh_flags[mi] = m.flags
            mesh_vertex_count[mi] = m.uvs.size // 2
            mesh_first_uv[mi] = uv_cursor
            uv_chunks.append(m.uvs)
            uv_cursor += m.uvs.size
            mesh_first_tri[mi] = tri_cursor
            mesh_tri_count[mi] = m.triangles.size
            tri_chunks.append(m.triangles)
            tri_cursor += m.triangles.size
            mesh_first_mask[mi] = len(mask_entries)
            mesh_mask_count[mi] = len(m.masks)
            mask_entries.extend(m.masks)
            mesh_first_color[mi] = color_count
            color_count += len(m.keyforms)
            for op, do, pos in m.keyforms:
                mesh_kf_opacity.append(op)
                mesh_kf_draw_order.append(do)
                mesh_kf_first_pos.append(push_positions(pos))
                ido = int(math.trunc(float(np.float32(do + 0.001))))
                min_do = min(min_do, ido)
                max_do = max(max_do, ido)

        if n_meshes == 0:
            min_do = 500
            max_do = 500

        # Official consistency-check position-run safeguard:
        # Official check tests keyform[i] with object[i]'s run length (even across objects).
        # Ensure positions_cursor >= max(first_pos[i] + 2 * obj_count[i]) for all i.
        required_pos_len = positions_cursor
        for i in range(min(len(warp_kf_first_pos), n_warps)):
            end_i = warp_kf_first_pos[i] + 2 * int(warp_point_count[i])
            if end_i > required_pos_len:
                required_pos_len = end_i
        for i in range(min(len(mesh_kf_first_pos), n_meshes)):
            end_i = mesh_kf_first_pos[i] + 2 * int(mesh_vertex_count[i])
            if end_i > required_pos_len:
                required_pos_len = end_i
        if required_pos_len > positions_cursor:
            positions_chunks.append(np.zeros(required_pos_len - positions_cursor, dtype=np.float32))
            positions_cursor = required_pos_len

        positions_arr = (
            np.concatenate(positions_chunks) if positions_chunks else np.zeros(0, dtype=np.float32)
        )
        uvs_arr = np.concatenate(uv_chunks) if uv_chunks else np.zeros(0, dtype=np.float32)
        tris_arr = np.concatenate(tri_chunks) if tri_chunks else np.zeros(0, dtype=np.uint16)

        # Draw-order group (single root group holding all ArtMeshes)
        group_first_obj = np.array([0], dtype=np.int32)
        group_obj_count = np.array([n_meshes], dtype=np.int32)
        group_entry_count = np.array([n_meshes], dtype=np.int32)
        group_max_do = np.array([max_do], dtype=np.int32)
        group_min_do = np.array([min_do], dtype=np.int32)
        group_obj_kind = np.zeros(n_meshes, dtype=np.int32)
        group_obj_index = np.arange(n_meshes, dtype=np.int32)
        group_obj_nested = np.full(n_meshes, -1, dtype=np.int32)

        # Assemble counts & values
        counts = np.zeros(COUNT_TABLE_LEN_V3_V4, dtype=np.int32)
        counts[C_PARTS] = n_parts
        counts[C_DEFORMERS] = n_defs
        counts[C_WARPS] = n_warps
        counts[C_ROTATIONS] = n_rots
        counts[C_ART_MESHES] = n_meshes
        counts[C_PARAMETERS] = len(self.params)
        counts[C_PART_KEYFORMS] = n_parts
        counts[C_WARP_KEYFORMS] = len(warp_kf_opacity)
        counts[C_ROTATION_KEYFORMS] = len(rot_kf_opacity)
        counts[C_ART_MESH_KEYFORMS] = len(mesh_kf_opacity)
        counts[C_POSITION_FLOATS] = positions_arr.size
        counts[C_BINDING_INDEX_ENTRIES] = len(binding_indices_pool)
        counts[C_BANDS] = len(band_first_entry)
        counts[C_PARAMETER_BINDINGS] = len(binding_first_key)
        counts[C_KEY_VALUES] = len(keys_pool)
        counts[C_UV_FLOATS] = uvs_arr.size
        counts[C_TRIANGLE_INDICES] = tris_arr.size
        counts[C_MASK_ENTRIES] = len(mask_entries)
        counts[C_DRAW_ORDER_GROUPS] = 1
        counts[C_DRAW_ORDER_GROUP_OBJECTS] = n_meshes
        if version >= 4:
            counts[C_MULTIPLY_COLORS] = color_count
            counts[C_SCREEN_COLORS] = color_count

        values: dict[str, object] = {
            "part.id": part_ids,
            "part.band": part_band,
            "part.firstKeyform": part_first_kf,
            "part.keyformCount": part_kf_count,
            "part.initiallyVisible": part_init_vis,
            "part.enabled": part_enabled,
            "part.parent": part_parent,
            "deformer.id": def_ids,
            "deformer.band": def_band,
            "deformer.visible": def_visible,
            "deformer.enabled": def_enabled,
            "deformer.part": def_part,
            "deformer.parent": def_parent,
            "deformer.kind": def_kind,
            "deformer.kindIndex": def_kind_idx,
            "warp.band": warp_band,
            "warp.firstKeyform": warp_first_kf,
            "warp.keyformCount": warp_kf_count,
            "warp.pointCount": warp_point_count,
            "warp.rows": warp_rows,
            "warp.columns": warp_cols,
            "warp.bilinear": warp_bilinear,
            "warp.firstColor": warp_first_color,
            "rotation.band": rot_band,
            "rotation.firstKeyform": rot_first_kf,
            "rotation.keyformCount": rot_kf_count,
            "rotation.baseAngle": rot_base_angle,
            "rotation.firstColor": rot_first_color,
            "mesh.id": mesh_ids,
            "mesh.band": mesh_band,
            "mesh.firstKeyform": mesh_first_kf,
            "mesh.keyformCount": mesh_kf_count,
            "mesh.visible": mesh_visible,
            "mesh.enabled": mesh_enabled,
            "mesh.part": mesh_part,
            "mesh.deformer": mesh_deformer,
            "mesh.texture": mesh_texture,
            "mesh.flags": mesh_flags,
            "mesh.vertexCount": mesh_vertex_count,
            "mesh.firstUv": mesh_first_uv,
            "mesh.firstTriangleIndex": mesh_first_tri,
            "mesh.triangleIndexCount": mesh_tri_count,
            "mesh.firstMask": mesh_first_mask,
            "mesh.maskCount": mesh_mask_count,
            "mesh.firstColor": mesh_first_color,
            "parameter.id": [p.id for p in self.params],
            "parameter.max": np.array([p.max_val for p in self.params], dtype=np.float32),
            "parameter.min": np.array([p.min_val for p in self.params], dtype=np.float32),
            "parameter.default": np.array([p.default_val for p in self.params], dtype=np.float32),
            "parameter.repeat": np.array([p.repeat for p in self.params], dtype=np.int32),
            "parameter.decimals": np.array([p.decimals for p in self.params], dtype=np.int32),
            "parameter.firstBinding": param_first_binding,
            "parameter.bindingCount": param_binding_count,
            "parameter.firstKey": param_first_key,
            "parameter.keyCount": param_key_count,
            "parameter.type": np.zeros(len(self.params), dtype=np.int32),
            "parameter.firstBlendShapeBinding": np.zeros(len(self.params), dtype=np.int32),
            "parameter.blendShapeBindingCount": np.zeros(len(self.params), dtype=np.int32),
            "partKeyform.drawOrder": part_kf_draw_order,
            "warpKeyform.opacity": np.array(warp_kf_opacity, dtype=np.float32),
            "warpKeyform.firstPosition": np.array(warp_kf_first_pos, dtype=np.int32),
            "rotationKeyform.opacity": np.array(rot_kf_opacity, dtype=np.float32),
            "rotationKeyform.angle": np.array(rot_kf_angle, dtype=np.float32),
            "rotationKeyform.originX": np.array(rot_kf_ox, dtype=np.float32),
            "rotationKeyform.originY": np.array(rot_kf_oy, dtype=np.float32),
            "rotationKeyform.scale": np.array(rot_kf_scale, dtype=np.float32),
            "rotationKeyform.mirrorX": np.array(rot_kf_mx, dtype=np.int32),
            "rotationKeyform.mirrorY": np.array(rot_kf_my, dtype=np.int32),
            "meshKeyform.opacity": np.array(mesh_kf_opacity, dtype=np.float32),
            "meshKeyform.drawOrder": np.array(mesh_kf_draw_order, dtype=np.float32),
            "meshKeyform.firstPosition": np.array(mesh_kf_first_pos, dtype=np.int32),
            "positions": positions_arr,
            "bindingIndex": np.array(binding_indices_pool, dtype=np.int32),
            "band.firstEntry": np.array(band_first_entry, dtype=np.int32),
            "band.entryCount": np.array(band_entry_count, dtype=np.int32),
            "binding.firstKey": np.array(binding_first_key, dtype=np.int32),
            "binding.keyCount": np.array(binding_key_count, dtype=np.int32),
            "keys": np.array(keys_pool, dtype=np.float32),
            "uvs": uvs_arr,
            "triangleIndices": tris_arr,
            "maskEntries": np.array(mask_entries, dtype=np.int32),
            "group.firstObject": group_first_obj,
            "group.objectCount": group_obj_count,
            "group.entryCount": group_entry_count,
            "group.maxDrawOrder": group_max_do,
            "group.minDrawOrder": group_min_do,
            "groupObject.kind": group_obj_kind,
            "groupObject.index": group_obj_index,
            "groupObject.nestedGroup": group_obj_nested,
        }

        if version >= 4:
            values["multiplyColor.r"] = np.ones(color_count, dtype=np.float32)
            values["multiplyColor.g"] = np.ones(color_count, dtype=np.float32)
            values["multiplyColor.b"] = np.ones(color_count, dtype=np.float32)
            values["screenColor.r"] = np.zeros(color_count, dtype=np.float32)
            values["screenColor.g"] = np.zeros(color_count, dtype=np.float32)
            values["screenColor.b"] = np.zeros(color_count, dtype=np.float32)

        return encode_moc3(
            version=version,
            ppu=self.ppu,
            origin_x=self.origin_x,
            origin_y=self.origin_y,
            width=self.width,
            height=self.height,
            canvas_flags=self.canvas_flags,
            counts=counts,
            values=values,
        )


def encode_moc3(
    version: int,
    ppu: float,
    origin_x: float,
    origin_y: float,
    width: float,
    height: float,
    canvas_flags: int,
    counts: np.ndarray,
    values: dict[str, object],
) -> bytes:
    fields = sorted([f for f in FIELD_TABLE if f[4] <= version], key=lambda f: f[1])
    offsets = np.zeros(SLOT_COUNT_V3_V4, dtype=np.uint32)
    end = HEADER_SIZE + SLOT_COUNT_V3_V4 * 4

    def place(size: int, packed: bool) -> int:
        nonlocal end
        start = end if (packed and size > 0) else _align64(end)
        if size > 0:
            end = start + size
        return start

    offsets[COUNT_TABLE_SLOT] = place(COUNT_TABLE_LEN_V3_V4 * 4, False)
    offsets[CANVAS_SLOT] = place(CANVAS_BLOCK_SIZE, False)

    placed: list[tuple[str, str, int, int]] = []
    for key, slot, ftype, count_idx, _ in fields:
        n = int(counts[count_idx])
        start = place(n * ELEMENT_SIZE[ftype], ftype == "name")
        offsets[slot] = start
        placed.append((key, ftype, start, n))

    total = _align64(end)
    buf = bytearray(total)

    # Header
    buf[0:4] = b"MOC3"
    buf[4] = version
    buf[5] = 0  # little-endian

    # Offset table
    buf[HEADER_SIZE : HEADER_SIZE + SLOT_COUNT_V3_V4 * 4] = offsets.astype("<u4").tobytes()

    # Count table
    ct_off = int(offsets[COUNT_TABLE_SLOT])
    buf[ct_off : ct_off + COUNT_TABLE_LEN_V3_V4 * 4] = counts.astype("<i4").tobytes()

    # Canvas block
    cv_off = int(offsets[CANVAS_SLOT])
    struct.pack_into("<fffffB", buf, cv_off, ppu, origin_x, origin_y, width, height, canvas_flags)

    # Sections
    for key, ftype, start, n in placed:
        if n == 0 or ftype == "placeholder":
            continue
        val = values.get(key)
        if val is None:
            continue
        if ftype == "name":
            for i, s in enumerate(val):  # type: ignore[arg-type]
                raw = str(s).encode("utf-8")
                if len(raw) > 63:
                    raise ValueError(f"ID too long (>63 UTF-8 bytes): {s!r}")
                at = start + i * 64
                buf[at : at + len(raw)] = raw
        elif ftype == "i32":
            arr = np.asarray(val, dtype="<i4")
            buf[start : start + n * 4] = arr.tobytes()
        elif ftype == "f32":
            arr = np.asarray(val, dtype="<f4")
            buf[start : start + n * 4] = arr.tobytes()
        elif ftype == "u16":
            arr = np.asarray(val, dtype="<u2")
            buf[start : start + n * 2] = arr.tobytes()
        elif ftype == "u8":
            arr = np.asarray(val, dtype=np.uint8)
            buf[start : start + n] = arr.tobytes()

    return bytes(buf)
