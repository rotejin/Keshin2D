"""Main Keshin2D -> Live2D Cubism (.moc3 + .model3.json + atlases + physics + expressions) compiler."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .atlas import AtlasEntry, build_atlases
from .expr_gen import DIFF_PARAM_MAP, KESHIN_EXPRS, build_expressions
from .keshin_math import DEG, PIV, KeshinMath, Pose, clamp, lerp, sstep
from .moc3_writer import Moc3Builder
from .physics_gen import build_physics3

# 5x5 sampling of head X/Y captures Keshin2D's nonlinear 3D face/hair turn accurately
HEAD_XY_KEYS = (-30.0, -15.0, 0.0, 15.0, 30.0)
BODY_X_KEYS = (-10.0, 0.0, 10.0)
BODY_Z_KEYS = (-10.0, 0.0, 10.0)
BREATH_KEYS = (0.0, 1.0)
SWAY_KEYS = (-1.0, 0.0, 1.0)


def _safe_id(prefix: str, raw: str, used: set[str]) -> str:
    """Create a valid ASCII/UTF-8 Cubism ID (<=63 bytes, unique)."""
    # Replace non-alnum with underscore; fallback to hex hash if all non-ASCII
    clean = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = raw.encode("utf-8").hex()[:12]
    cand = f"{prefix}_{clean}"[:56]
    base = cand
    n = 2
    while cand in used:
        cand = f"{base}_{n}"
        n += 1
    used.add(cand)
    return cand


def _grid_mesh_for_entry(
    entry: AtlasEntry,
    cell: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create a regular grid mesh strictly covering the cropped sprite rect of an AtlasEntry.

    Returns:
        rest_xy: float64 shape (V, 2) in Keshin2D model pixel coords
        uvs: float32 shape (2*V,)
        tris: uint16 shape (3*T,)
    """
    x0 = entry.layer_x + entry.crop_x
    y0 = entry.layer_y + entry.crop_y
    w = float(entry.crop_w)
    h = float(entry.crop_h)
    nx = max(2, min(40, int(math.ceil(w / cell))))
    ny = max(2, min(40, int(math.ceil(h / cell))))

    xs = np.linspace(x0, x0 + w, nx + 1)
    ys = np.linspace(y0, y0 + h, ny + 1)
    gx, gy = np.meshgrid(xs, ys)  # shape (ny+1, nx+1)
    rx = gx.reshape(-1)
    ry = gy.reshape(-1)
    rest_xy = np.stack([rx, ry], axis=-1)

    u, v = entry.uv_for_model_xy(rx, ry)
    uvs = np.empty(rx.size * 2, dtype=np.float32)
    uvs[0::2] = u
    uvs[1::2] = v

    tris: list[int] = []
    stride = nx + 1
    for j in range(ny):
        row0 = j * stride
        row1 = row0 + stride
        for i in range(nx):
            a = row0 + i
            b = a + 1
            c = row1 + i
            d = c + 1
            tris.extend((a, b, c, b, d, c))
    return rest_xy, uvs, np.array(tris, dtype=np.uint16)


class _WarpBox:
    """Tracks a bilinear WarpDeformer's rest bounding box for child UV normalization."""

    def __init__(self, def_idx: int, x0: float, y0: float, x1: float, y1: float) -> None:
        self.def_idx = def_idx
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.w = max(1.0, x1 - x0)
        self.h = max(1.0, y1 - y0)

    def to_local(self, xy: np.ndarray) -> np.ndarray:
        """Convert Keshin2D pixel coords (V, 2) -> normalized [0, 1] flat float32 array."""
        out = np.empty(xy.shape[0] * 2, dtype=np.float32)
        out[0::2] = ((xy[:, 0] - self.x0) / self.w).astype(np.float32)
        out[1::2] = ((xy[:, 1] - self.y0) / self.h).astype(np.float32)
        return out


def convert_keshin_to_cubism(
    model_dir: Path,
    out_dir: Path,
    model_name: Optional[str] = None,
    moc_version: int = 3,
    atlas_size: int = 4096,
) -> dict:
    """Convert a Keshin2D model directory (model.json + parts/*.png) into a Live2D Cubism model folder."""
    model_dir = Path(model_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model = json.loads((model_dir / "model.json").read_text(encoding="utf-8"))
    parts_dir = model_dir / "parts"
    name = model_name or model_dir.name
    km = KeshinMath(model)

    # 1. Decide which layers are actually needed (skip unused hidden fallback layers & o20/o50/o70/wide textures)
    has_key_eye = bool(model.get("keyEye"))
    has_key_mouth = bool(model.get("keyMouth"))
    needed_layers: list[dict] = []
    for L in model["layers"]:
        ln = L["name"]
        lp = L["path"]
        if L.get("opacity", 1.0) <= 0.0:
            continue
        if has_key_eye and ln.startswith("目キー_"):
            # keyshape.js only uses open/closed/smileClosed/smileNarrow/sad/glare/jito/shut/under/corner/crease textures
            stem = ln[len("目キー_") : -1]
            if stem in ("o20", "o50", "o70", "wide"):
                continue
            needed_layers.append(L)
            continue
        if has_key_eye and lp.startswith("頭/顔/瞳") and L.get("hidden"):
            continue
        if has_key_mouth and lp.startswith("頭/顔/口"):
            if ln.startswith("口キー_"):
                needed_layers.append(L)
            continue
        if lp.startswith("表情差分"):
            needed_layers.append(L)
            continue
        if L.get("hidden"):
            continue
        needed_layers.append(L)

    # 2. Pack textures into 4096x4096 PNG atlases
    atlas_pages, entries = build_atlases(needed_layers, parts_dir, atlas_size=atlas_size)
    tex_subdir_name = f"{name}.{atlas_size}"
    tex_subdir = out_dir / tex_subdir_name
    tex_subdir.mkdir(parents=True, exist_ok=True)
    tex_rel_paths: list[str] = []
    for ti, page_img in enumerate(atlas_pages):
        rel = f"{tex_subdir_name}/texture_{ti:02d}.png"
        page_img.save(out_dir / rel, format="PNG", optimize=True)
        tex_rel_paths.append(rel)

    # 3. Compute canvas bounds in Keshin2D coordinates -> Live2D model units
    all_x0 = min((e.layer_x + e.crop_x for e in entries.values()), default=0.0)
    all_y0 = min((e.layer_y + e.crop_y for e in entries.values()), default=0.0)
    all_x1 = max((e.layer_x + e.crop_x + e.crop_w for e in entries.values()), default=3000.0)
    all_y1 = max((e.layer_y + e.crop_y + e.crop_h for e in entries.values()), default=float(km.BODY_BOTTOM))

    pad_box = 180.0
    cv_w = max(3000.0, (all_x1 - all_x0) + 2 * pad_box)
    cv_h = (all_y1 - all_y0) + 2 * pad_box
    origin_x = 1500.0
    origin_y = 0.5 * (all_y0 + all_y1)
    ppu = max(cv_w, cv_h) * 0.5

    def to_model_xy(x: float, y: float) -> tuple[float, float]:
        return (x - origin_x) / ppu, (y - origin_y) / ppu

    def to_head_local_xy(x: float, y: float) -> tuple[float, float]:
        return (x - PIV[0]) / ppu, (y - PIV[1]) / ppu

    b = Moc3Builder(
        pixels_per_unit=ppu,
        origin_x=origin_x - (1500.0 - cv_w * 0.5),
        origin_y=origin_y - (all_y0 - pad_box),
        width=cv_w,
        height=cv_h,
        flags=0,
    )

    used_ids: set[str] = set()
    cdi_params: list[dict] = []
    cdi_parts: list[dict] = []

    def reg_param(
        pid: str,
        pmin: float,
        pdef: float,
        pmax: float,
        label: str,
        group_id: str = "",
    ) -> str:
        b.add_parameter(pid, pmin, pdef, pmax)
        if not any(p["Id"] == pid for p in cdi_params):
            cdi_params.append({"Id": pid, "GroupId": group_id, "Name": label})
        return pid

    def reg_part(pid: str, label: str, parent: int = -1) -> int:
        idx = b.add_part(pid, parent=parent)
        if not any(p["Id"] == pid for p in cdi_parts):
            cdi_parts.append({"Id": pid, "Name": label})
        return idx

    # 4. Register standard VTube Studio / Cubism Parameters
    reg_param("ParamAngleX", -30.0, 0.0, 30.0, "Angle X", "GroupHead")
    reg_param("ParamAngleY", -30.0, 0.0, 30.0, "Angle Y", "GroupHead")
    reg_param("ParamAngleZ", -30.0, 0.0, 30.0, "Angle Z", "GroupHead")
    reg_param("ParamBodyAngleX", -10.0, 0.0, 10.0, "Body X", "GroupBody")
    reg_param("ParamBodyAngleZ", -10.0, 0.0, 10.0, "Body Z", "GroupBody")
    reg_param("ParamBreath", 0.0, 0.0, 1.0, "Breath", "GroupBody")

    reg_param("ParamEyeLOpen", 0.0, 1.0, 1.2, "Eye L Open", "GroupEye")
    reg_param("ParamEyeROpen", 0.0, 1.0, 1.2, "Eye R Open", "GroupEye")
    reg_param("ParamEyeLSmile", 0.0, 0.0, 1.0, "Eye L Smile", "GroupEye")
    reg_param("ParamEyeRSmile", 0.0, 0.0, 1.0, "Eye R Smile", "GroupEye")
    reg_param("ParamEyeBallX", -1.0, 0.0, 1.0, "Eyeball X", "GroupEye")
    reg_param("ParamEyeBallY", -1.0, 0.0, 1.0, "Eyeball Y", "GroupEye")
    reg_param("ParamIrisSize", -1.0, 0.0, 1.0, "Iris Size", "GroupEye")
    reg_param("ParamEyeExprHide", 0.0, 0.0, 1.0, "Hide Normal Eye", "GroupExpr")
    reg_param("ParamEyeSad", 0.0, 0.0, 1.0, "Eye Sad", "GroupExpr")
    reg_param("ParamEyeGlare", 0.0, 0.0, 1.0, "Eye Glare", "GroupExpr")
    reg_param("ParamEyeJito", 0.0, 0.0, 1.0, "Eye Jito", "GroupExpr")
    reg_param("ParamEyeShut", 0.0, 0.0, 1.0, "Eye Shut", "GroupExpr")

    reg_param("ParamBrowLY", -1.0, 0.0, 1.0, "Brow L Y", "GroupBrow")
    reg_param("ParamBrowRY", -1.0, 0.0, 1.0, "Brow R Y", "GroupBrow")
    reg_param("ParamBrowLAngle", -1.0, 0.0, 1.0, "Brow L Angle", "GroupBrow")
    reg_param("ParamBrowRAngle", -1.0, 0.0, 1.0, "Brow R Angle", "GroupBrow")
    reg_param("ParamBrowLForm", -1.0, 0.0, 1.0, "Brow L Form", "GroupBrow")
    reg_param("ParamBrowRForm", -1.0, 0.0, 1.0, "Brow R Form", "GroupBrow")
    reg_param("ParamBrowShow", 0.0, 0.0, 1.0, "Brow Over Hair", "GroupBrow")

    reg_param("ParamMouthOpenY", 0.0, 0.0, 1.0, "Mouth Open", "GroupMouth")
    reg_param("ParamMouthForm", -1.0, 0.0, 1.0, "Mouth Form", "GroupMouth")
    reg_param("ParamMouthExprHide", 0.0, 0.0, 1.0, "Hide Normal Mouth", "GroupExpr")

    reg_param("ParamCheek", 0.0, 0.0, 1.0, "Cheek Blush", "GroupExpr")
    reg_param("ParamHairFront", -1.0, 0.0, 1.0, "Hair Front Sway", "GroupPhysics")
    reg_param("ParamHairSide", -1.0, 0.0, 1.0, "Hair Side Sway", "GroupPhysics")
    reg_param("ParamHairBack", -1.0, 0.0, 1.0, "Hair Back Sway", "GroupPhysics")

    # Register custom physics parameters from model.physics
    phys_by_layer: dict[str, tuple[str, dict]] = {}
    phys_specs_list: list[tuple[str, dict]] = []
    phys_by_id: dict[str, dict] = {}
    for spec in model.get("physics") or []:
        layers_list = spec.get("layers") or []
        if not layers_list or layers_list[0] not in km.by_name:
            continue
        pid = _safe_id("ParamPhys", spec["id"], used_ids)
        reg_param(pid, -1.0, 0.0, 1.0, spec.get("label", spec["id"]), "GroupPhysics")
        phys_specs_list.append((pid, spec))
        phys_by_id[spec["id"]] = spec
        for ln in layers_list:
            phys_by_layer[ln] = (pid, spec)

    # Register expression diff parameters for diffs present in this model
    for L in needed_layers:
        if L["path"].startswith("表情差分"):
            key = re.sub(r"[RL]$", "", L["name"])
            dpid = DIFF_PARAM_MAP.get(key)
            if dpid and dpid != "ParamCheek":
                reg_param(dpid, 0.0, 0.0, 1.0, key, "GroupExpr")

    # Register expression mouth parameters
    expr_mouth_keys = [
        "omega", "wavy", "grin", "tri", "round", "smug", "pout", "square",
        "laugh", "he", "small", "u", "a",
    ]
    if has_key_mouth:
        km_keys = model["keyMouth"]["keys"]
        for mk in expr_mouth_keys:
            if mk in km_keys and f"口キー_{mk}" in entries:
                reg_param(f"ParamMouthExpr_{mk}", 0.0, 0.0, 1.0, f"Mouth {mk}", "GroupExpr")

    # 5. Parts
    part_root = reg_part("Part_Root", name)
    part_body = reg_part("Part_Body", "Body", part_root)
    part_head = reg_part("Part_Head", "Head", part_root)
    part_face = reg_part("Part_Face", "Face", part_head)
    part_eye_r = reg_part("Part_EyeR", "Eye R", part_head)
    part_eye_l = reg_part("Part_EyeL", "Eye L", part_head)
    part_brow = reg_part("Part_Brow", "Eyebrows", part_head)
    part_mouth = reg_part("Part_Mouth", "Mouth", part_head)
    part_hair_front = reg_part("Part_HairFront", "Front Hair", part_head)
    part_hair_back = reg_part("Part_HairBack", "Back Hair", part_head)
    part_expr = reg_part("Part_Expr", "Expression Overlays", part_head)

    # 6. Build Root Body WarpDeformer & Head Roll RotationDeformer
    body_x0 = min(200.0, all_x0 - 200.0)
    body_x1 = max(2800.0, all_x1 + 200.0)
    body_y0 = min(-400.0, all_y0 - 200.0)
    body_y1 = max(km.BODY_BOTTOM + 200.0, all_y1 + 200.0)

    def make_body_warp() -> _WarpBox:
        rows, cols = 6, 4
        xs = np.linspace(body_x0, body_x1, cols + 1)
        ys = np.linspace(body_y0, body_y1, rows + 1)
        axes = [
            ("ParamBodyAngleX", BODY_X_KEYS),
            ("ParamBodyAngleZ", BODY_Z_KEYS),
            ("ParamBreath", BREATH_KEYS),
        ]
        # Innermost axis FIRST: BodyAngleX fastest, then BodyAngleZ, then Breath outermost
        kfs = []
        for br in BREATH_KEYS:
            for bz in BODY_Z_KEYS:
                for bx in BODY_X_KEYS:
                    pts = np.empty((rows + 1) * (cols + 1) * 2, dtype=np.float32)
                    k = 0
                    for gy in ys:
                        for gx in xs:
                            mx, my = km.body_t(float(gx), float(gy), bx, bz, br)
                            ux, uy = to_model_xy(mx, my)
                            pts[k] = ux
                            pts[k + 1] = uy
                            k += 2
                    kfs.append((1.0, pts))
        d_idx = b.add_warp_deformer("Warp_Body", -1, part_body, rows, cols, axes, kfs, bilinear=1)
        return _WarpBox(d_idx, body_x0, body_y0, body_x1, body_y1)

    warp_body = make_body_warp()

    # Head RotationDeformer (child of Warp_Body, anchored at PIV in Warp_Body normalized coords)
    piv_u = (PIV[0] - warp_body.x0) / warp_body.w
    piv_v = (PIV[1] - warp_body.y0) / warp_body.h
    roll_max = min(km.tune["rollMax"], 22.0)
    rot_head_z = b.add_rotation_deformer(
        "Rot_HeadZ",
        warp_body.def_idx,
        part_head,
        axes=[("ParamAngleZ", (-30.0, 0.0, 30.0))],
        keyforms=[
            (1.0, -roll_max, piv_u, piv_v, 1.0, 0, 0),
            (1.0, 0.0, piv_u, piv_v, 1.0, 0, 0),
            (1.0, roll_max, piv_u, piv_v, 1.0, 0, 0),
        ],
    )

    # Precompute 5x5 Pose table for Head XY WarpDeformers
    poses_xy: list[Pose] = []
    for ay in HEAD_XY_KEYS:
        for ax in HEAD_XY_KEYS:
            poses_xy.append(km.make_pose(ax, ay))

    def make_head_xy_warp(
        wid: str,
        part_idx: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        rows: int,
        cols: int,
        map_fn: Callable[[float, float, Pose], tuple[float, float]],
    ) -> _WarpBox:
        xs = np.linspace(x0, x1, cols + 1)
        ys = np.linspace(y0, y1, rows + 1)
        axes = [("ParamAngleX", HEAD_XY_KEYS), ("ParamAngleY", HEAD_XY_KEYS)]
        kfs = []
        for pose in poses_xy:
            pts = np.empty((rows + 1) * (cols + 1) * 2, dtype=np.float32)
            k = 0
            for gy in ys:
                for gx in xs:
                    ox, oy = map_fn(float(gx), float(gy), pose)
                    lx, ly = to_head_local_xy(ox, oy)
                    pts[k] = lx
                    pts[k + 1] = ly
                    k += 2
            kfs.append((1.0, pts))
        d_idx = b.add_warp_deformer(wid, rot_head_z, part_idx, rows, cols, axes, kfs, bilinear=1)
        return _WarpBox(d_idx, x0, y0, x1, y1)

    def bbox_of(names: list[str], pad: float = 120.0, default: tuple[float, float, float, float] = (800, 0, 2200, 1400)):
        es = [entries[n] for n in names if n in entries]
        if not es:
            return default
        x0 = min(e.layer_x + e.crop_x for e in es) - pad
        y0 = min(e.layer_y + e.crop_y for e in es) - pad
        x1 = max(e.layer_x + e.crop_x + e.crop_w for e in es) + pad
        y1 = max(e.layer_y + e.crop_y + e.crop_h for e in es) + pad
        return x0, y0, x1, y1

    # 7. Create Head-XY WarpDeformers (dense 18x14 face grid tightly fitted to eliminate jawline kinks)
    face_box = bbox_of(
        [L["name"] for L in needed_layers if L["path"].startswith("頭/顔/輪郭")],
        pad=60.0, default=(1040.0, 60.0, 1960.0, 1220.0),
    )
    warp_face_skin = make_head_xy_warp(
        "Warp_FaceSkin", part_face, *face_box, 18, 14,
        lambda x, y, pose: km.surf_map(km.SKIN, x, y, pose),
    )
    warp_face_shade = make_head_xy_warp(
        "Warp_FaceShade", part_face, *face_box, 14, 10,
        lambda x, y, pose: km.surf_map(km.SHADE, x, y, pose),
    )

    c_er = model["curves"]["eyeR"]["iris"]
    c_el = model["curves"]["eyeL"]["iris"]
    warp_eye_r = make_head_xy_warp(
        "Warp_EyeR", part_eye_r, c_er[0] - 260, c_er[1] - 200, c_er[0] + 260, c_er[1] + 200, 4, 4,
        lambda x, y, pose: km.group_apply(km.eye_group_spec["R"], x, y, pose),
    )
    warp_eye_l = make_head_xy_warp(
        "Warp_EyeL", part_eye_l, c_el[0] - 260, c_el[1] - 200, c_el[0] + 260, c_el[1] + 200, 4, 4,
        lambda x, y, pose: km.group_apply(km.eye_group_spec["L"], x, y, pose),
    )
    warp_eyes = {"R": warp_eye_r, "L": warp_eye_l}

    c_br = model["curves"]["browR"]
    c_bl = model["curves"]["browL"]
    warp_brow_r = make_head_xy_warp(
        "Warp_BrowR", part_brow, c_br[0] - 240, c_br[1] - 120, c_br[0] + 240, c_br[1] + 120, 3, 4,
        lambda x, y, pose: km.group_apply(km.brow_group_spec["R"], x, y, pose),
    )
    warp_brow_l = make_head_xy_warp(
        "Warp_BrowL", part_brow, c_bl[0] - 240, c_bl[1] - 120, c_bl[0] + 240, c_bl[1] + 120, 3, 4,
        lambda x, y, pose: km.group_apply(km.brow_group_spec["L"], x, y, pose),
    )
    warp_brows = {"R": warp_brow_r, "L": warp_brow_l}

    # Wrapper deformer for hair-over eyebrows opacity (ParamBrowShow)
    def make_opacity_wrapper(wid: str, parent_warp: _WarpBox, part_idx: int, param_id: str, op0: float, op1: float) -> _WarpBox:
        g = np.array([0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0], dtype=np.float32)
        d_idx = b.add_warp_deformer(
            wid, parent_warp.def_idx, part_idx, 1, 1,
            axes=[(param_id, (0.0, 1.0))],
            keyforms=[(op0, g), (op1, g)],
            bilinear=1,
        )
        return _WarpBox(d_idx, parent_warp.x0, parent_warp.y0, parent_warp.x1, parent_warp.y1)

    warp_brow_over = {
        "R": make_opacity_wrapper("Warp_BrowOverR", warp_brow_r, part_brow, "ParamBrowShow", 0.0, 0.92),
        "L": make_opacity_wrapper("Warp_BrowOverL", warp_brow_l, part_brow, "ParamBrowShow", 0.0, 0.92),
    }

    mc = model["curves"]["mouth"]
    mcx = 0.5 * (mc["xa"] + mc["xb"])
    myc = 0.5 * (mc["Y"][0] + mc["Y"][-1])
    warp_mouth = make_head_xy_warp(
        "Warp_Mouth", part_mouth, mcx - 260, myc - 180, mcx + 260, myc + 240, 4, 6,
        lambda x, y, pose: km.group_apply(km.mouth_group_spec, x, y, pose),
    )
    warp_mouth_normal = make_opacity_wrapper(
        "Warp_MouthNormal", warp_mouth, part_mouth, "ParamMouthExprHide", 1.0, 0.0
    )

    nose_box = bbox_of([L["name"] for L in needed_layers if L["path"] == "頭/顔/鼻"], pad=60.0, default=(1420, 780, 1580, 960))
    warp_nose = make_head_xy_warp(
        "Warp_Nose", part_face, *nose_box, 3, 3,
        lambda x, y, pose: km.group_apply(km.nose_group_spec, x, y, pose),
    )

    has_clumps = bool(model.get("hairClumps"))
    front_hair_names = [L["name"] for L in needed_layers if L["path"] == "頭/前髪" and L["name"] not in phys_by_layer]
    fh_box = bbox_of(front_hair_names, pad=360.0, default=(600, -100, 2400, 1550))
    fh_shell = km.SHELL["clumpFront"] if has_clumps else km.SHELL["bangs"]
    warp_front_hair = make_head_xy_warp(
        "Warp_FrontHair", part_hair_front, *fh_box, 10, 8,
        lambda x, y, pose: km.surf_map(fh_shell, x, y, pose),
    )

    back_hair_names = [L["name"] for L in needed_layers if L["path"] in ("後ろ髪", "結び髪") and L["name"] not in phys_by_layer]
    bh_box = bbox_of(back_hair_names, pad=360.0, default=(600, -50, 2400, 1650))
    bh_shell = km.SHELL["clumpBack"] if has_clumps else km.SHELL["back2"]
    warp_back_hair = make_head_xy_warp(
        "Warp_BackHair", part_hair_back, *bh_box, 10, 8,
        lambda x, y, pose: km.surf_map(bh_shell, x, y, pose),
    )

    # Optional warps: Ear, Hat, EyeFollow, Pin, and per-physics Frame warps
    warp_ear: Optional[_WarpBox] = None
    ear_names = [L["name"] for L in needed_layers if L["path"] == "頭/耳" and L["name"] not in phys_by_layer]
    if ear_names:
        eb = bbox_of(ear_names, pad=100.0)
        warp_ear = make_head_xy_warp("Warp_Ear", part_head, *eb, 6, 6, lambda x, y, pose: km.ear_deform(x, y, pose))

    warp_hat: Optional[_WarpBox] = None
    hat_names = [L["name"] for L in needed_layers if L["path"] == "頭/帽子"]
    if hat_names:
        hb = bbox_of(hat_names, pad=160.0)
        warp_hat = make_head_xy_warp(
            "Warp_Hat", part_head, *hb, 8, 8,
            lambda x, y, pose: km.surf_map(km.SHELL["hat"], x, y, pose),
        )

    warp_eye_follow: Optional[_WarpBox] = None
    eye_follow_names = list(model.get("eyeAttach") or [])
    for k_diff, v_att in (model.get("diffAttach") or {}).items():
        if v_att == "eye":
            eye_follow_names.extend(L["name"] for L in needed_layers if L["path"].startswith("表情差分") and re.sub(r"[RL]$", "", L["name"]) == k_diff)
    if eye_follow_names:
        efb = bbox_of(eye_follow_names, pad=100.0)
        def _ef_map(x: float, y: float, pose: Pose) -> tuple[float, float]:
            w = sstep(km.HX - 50.0, km.HX + 50.0, x)
            oa = km.group_apply(km.eye_group_spec["R"], x, y, pose)
            ob = km.group_apply(km.eye_group_spec["L"], x, y, pose)
            return lerp(oa[0], ob[0], w), lerp(oa[1], ob[1], w)
        warp_eye_follow = make_head_xy_warp("Warp_EyeFollow", part_face, *efb, 6, 8, _ef_map)

    # Per-physics-item parent attach warps
    phys_parent_warps: dict[str, _WarpBox] = {}
    for _, spec in phys_specs_list:
        sid = spec["id"]
        chain = [spec]
        cur_p = phys_by_id.get(spec.get("parent", ""))
        while cur_p and len(chain) < 4:
            chain.append(cur_p)
            cur_p = phys_by_id.get(cur_p.get("parent", ""))
        fo = None
        for c in chain:
            if c.get("frame"):
                fo = c
        att = spec.get("attach", "hat")
        pb = bbox_of(spec.get("layers", []), pad=160.0)
        if fo is not None:
            base_L = km.by_name[fo["layers"][0]]
            pv = fo.get("pivot", [0.5, 0.0])
            ax0 = base_L["x"] + pv[0] * base_L["w"]
            ay0 = base_L["y"] + pv[1] * base_L["h"]
            f_spec = fo["frame"]
            stand_def = fo.get("type") == "sprout"
            phys_parent_warps[sid] = make_head_xy_warp(
                _safe_id("Warp_PhysFrame", sid, used_ids),
                part_head, *pb, 4, 4,
                lambda x, y, pose, fs=f_spec, a0=ax0, b0=ay0, sd=stand_def: km.frame_apply(fs, a0, b0, x, y, pose, sd),
            )
        elif att == "body":
            phys_parent_warps[sid] = warp_body
        elif att == "skin":
            phys_parent_warps[sid] = warp_face_skin
        elif att == "pin":
            phys_parent_warps[sid] = make_head_xy_warp(
                _safe_id("Warp_PhysPin", sid, used_ids), part_head, *pb, 4, 4,
                lambda x, y, pose: km.group_apply(km.pin_group_spec, x, y, pose),
            )
        else:
            if warp_hat is None:
                warp_hat = make_head_xy_warp(
                    "Warp_Hat", part_head, *pb, 6, 6,
                    lambda x, y, pose: km.surf_map(km.SHELL["hat"], x, y, pose),
                )
            phys_parent_warps[sid] = warp_hat

    # Rigid pins (chiwa / kurage02)
    rigid_pin_warps: dict[str, _WarpBox] = {}
    for pname, pspec in (model.get("rigidPins") or {}).items():
        if pname not in entries:
            continue
        L = km.by_name[pname]
        pb = bbox_of([pname], pad=80.0)
        ax0 = L["x"] + L["w"] * 0.5
        ay0 = L["y"] + L["h"] * 0.5
        rigid_pin_warps[pname] = make_head_xy_warp(
            _safe_id("Warp_Pin", pname, used_ids), part_head, *pb, 4, 4,
            lambda x, y, pose, fs=pspec, a0=ax0, b0=ay0: km.frame_apply(fs, a0, b0, x, y, pose, False),
        )

    # 8. Build Eye helper structures (Normal Eye wrapper + Iris gaze/scale wrapper)
    warp_eye_normal = {
        k: make_opacity_wrapper(f"Warp_EyeNormal{k}", warp_eyes[k], part_eye_r if k == "R" else part_eye_l, "ParamEyeExprHide", 1.0, 0.0)
        for k in ("R", "L")
    }

    warp_iris: dict[str, _WarpBox] = {}
    for k in ("R", "L"):
        ew = warp_eyes[k]
        pidx = part_eye_r if k == "R" else part_eye_l
        ecx, ecy = model["curves"][f"eye{k}"]["iris"]
        # First child warp: iris scale (ParamIrisSize [-1, 0, 1])
        scale_axes = [("ParamIrisSize", (-1.0, 0.0, 1.0))]
        scale_kfs = []
        for s_val in (-1.0, 0.0, 1.0):
            ik = 1.0 + 0.2 * s_val
            pts = np.empty(4 * 2, dtype=np.float32)
            corners = [(ew.x0, ew.y0), (ew.x1, ew.y0), (ew.x0, ew.y1), (ew.x1, ew.y1)]
            for ci, (cxp, cyp) in enumerate(corners):
                nx = ecx + (cxp - ecx) * ik
                ny = ecy + (cyp - ecy) * ik
                pts[ci * 2] = (nx - ew.x0) / ew.w
                pts[ci * 2 + 1] = (ny - ew.y0) / ew.h
            scale_kfs.append((1.0, pts))
        d_scale = b.add_warp_deformer(f"Warp_IrisScale{k}", ew.def_idx, pidx, 1, 1, scale_axes, scale_kfs, bilinear=1)

        # Second child warp: gaze shift (ParamEyeBallX [-1, 0, 1] x ParamEyeBallY [-1, 0, 1])
        # Note: Live2D ParamEyeBallY = +1 means looking UP (-y in y-down coords)!
        gaze_axes = [("ParamEyeBallX", (-1.0, 0.0, 1.0)), ("ParamEyeBallY", (-1.0, 0.0, 1.0))]
        gaze_kfs = []
        for gy_val in (-1.0, 0.0, 1.0):
            for gx_val in (-1.0, 0.0, 1.0):
                dx_u = (gx_val * 22.0) / ew.w
                dy_v = (-gy_val * 15.0) / ew.h
                pts = np.array([
                    0.0 + dx_u, 0.0 + dy_v,
                    1.0 + dx_u, 0.0 + dy_v,
                    0.0 + dx_u, 1.0 + dy_v,
                    1.0 + dx_u, 1.0 + dy_v,
                ], dtype=np.float32)
                gaze_kfs.append((1.0, pts))
        d_gaze = b.add_warp_deformer(f"Warp_IrisGaze{k}", d_scale, pidx, 1, 1, gaze_axes, gaze_kfs, bilinear=1)
        warp_iris[k] = _WarpBox(d_gaze, ew.x0, ew.y0, ew.x1, ew.y1)

    # 9. Emit ArtMeshes in EXACT Keshin2D draw order (matching avatar.js lines 2034-2062)
    draw_order_cursor = 100.0
    DRAW_STEP = 5.0

    def next_do() -> float:
        nonlocal draw_order_cursor
        v = draw_order_cursor
        draw_order_cursor += DRAW_STEP
        return min(995.0, v)

    face_mask_idx: Optional[int] = None
    white_mask_idx: dict[str, int] = {}
    deferred_face_clips: list[int] = []

    def layer_flags(L: dict) -> int:
        # Bit 2 (4) = double-sided; Bit 1 (2) = multiply blend
        f = 4
        if L.get("blend") == "multiply":
            f |= 2
        return f

    # Helpers to emit each layer type cleanly
    def emit_simple_layer(
        L: dict,
        parent_warp: _WarpBox,
        part_idx: int,
        cell: float = 28.0,
        clip_face: bool = False,
        clip_eye: Optional[str] = None,
        diff_param: Optional[str] = None,
        mesh_id_override: Optional[str] = None,
    ) -> Optional[int]:
        entry = entries.get(L["name"])
        if entry is None:
            return None
        rest_xy, uvs, tris = _grid_mesh_for_entry(entry, cell)
        pos_local = parent_warp.to_local(rest_xy)
        base_op = float(L.get("opacity", 1.0))
        do = next_do()
        mid = mesh_id_override or _safe_id("Mesh", L["name"], used_ids)

        masks: list[int] = []
        if clip_eye and clip_eye in white_mask_idx:
            masks.append(white_mask_idx[clip_eye])
        elif clip_face and face_mask_idx is not None:
            masks.append(face_mask_idx)

        if diff_param:
            axes = [(diff_param, (0.0, 1.0))]
            kfs = [(0.0, do, pos_local), (base_op, do, pos_local)]
        else:
            axes = []
            kfs = [(base_op, do, pos_local)]

        m_idx = b.add_art_mesh(
            mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L),
            uvs, tris, axes, kfs, masks=masks,
        )
        if clip_face and face_mask_idx is None and not clip_eye:
            deferred_face_clips.append(m_idx)
        return m_idx

    def emit_hair_layer(L: dict) -> None:
        entry = entries.get(L["name"])
        if entry is None:
            return
        ln = L["name"]
        lp = L["path"]
        is_back = lp in ("後ろ髪", "結び髪")
        parent_warp = warp_back_hair if is_back else warp_front_hair
        part_idx = part_hair_back if is_back else part_hair_front
        locks = model.get("hairLocks") or {}
        clumps = model.get("hairClumps") or {}
        hfield = model.get("hairField") or {}
        hbases = model.get("hairBases") or {}
        rigid_list = set(model.get("hairRigid") or [])

        # Rigid back cap / braided rigid hair: no sway needed
        if ln == "後頭部" or ln in rigid_list:
            emit_simple_layer(L, parent_warp, part_idx, cell=36.0)
            return

        rest_xy, uvs, tris = _grid_mesh_for_entry(entry, 30.0)
        do = next_do()
        base_op = float(L.get("opacity", 1.0))
        mid = _safe_id("Mesh_Hair", ln, used_ids)

        if clumps and ln in clumps:
            c = clumps[ln]
            grp = c.get("g", "bangs")
            pid = "ParamHairBack" if grp == "back" else ("ParamHairSide" if grp == "side" else "ParamHairFront")
            u_side = clamp((c["tip"][0] - km.HX) / (1.15 * km.R0), -1.0, 1.0)
            max_phi = 0.24 if grp == "bangs" else (0.34 if grp == "side" else 0.36)
            kfs = []
            for sv in SWAY_KEYS:
                phi = sv * max_phi
                pts = np.empty_like(rest_xy)
                for vi in range(rest_xy.shape[0]):
                    pts[vi, 0], pts[vi, 1] = km.clump_bend(c["root"], c["tip"], grp, float(rest_xy[vi, 0]), float(rest_xy[vi, 1]), phi, u_side)
                kfs.append((base_op, do, parent_warp.to_local(pts)))
            b.add_art_mesh(mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, [(pid, SWAY_KEYS)], kfs)
            return

        if hfield and (ln in locks or ln in hbases):
            part_key = "back" if is_back else "front"
            F = hfield[part_key]
            top_y = float(F["top"])
            if part_key == "back":
                flen = float(F["len"])
                pid = "ParamHairBack"
                kfs = []
                for sv in SWAY_KEYS:
                    phi = sv * 0.14
                    phi2 = phi * 1.4
                    pts = rest_xy.copy()
                    t = np.clip((pts[:, 1] - top_y) / max(flen, 1.0), 0.0, 1.15)
                    pts[:, 0] += flen * (phi * 0.7 * (t ** 1.6) + phi2 * 0.5 * (t ** 3))
                    kfs.append((base_op, do, parent_warp.to_local(pts)))
                b.add_art_mesh(mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, [(pid, SWAY_KEYS)], kfs)
                return

            # Front hairLocks / hairBase: unify flow smoothly across bangs (center) and side locks!
            flen = float(F["sideLen"])
            sx0 = float(F.get("sideX0", 260.0))
            sx1 = float(F.get("sideX1", 390.0))
            if ln in locks:
                grp = locks[ln].get("g", "side")
                pid = "ParamHairFront" if grp == "bangs" else "ParamHairSide"
                amp = 0.12 if grp == "bangs" else 0.14
                kfs = []
                for sv in SWAY_KEYS:
                    phi = sv * amp
                    phi2 = phi * 1.4
                    pts = rest_xy.copy()
                    t = np.clip((pts[:, 1] - top_y) / max(flen, 1.0), 0.0, 1.15)
                    pts[:, 0] += flen * (phi * 0.7 * (t ** 1.6) + phi2 * 0.5 * (t ** 3))
                    kfs.append((base_op, do, parent_warp.to_local(pts)))
                b.add_art_mesh(mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, [(pid, SWAY_KEYS)], kfs)
            else:
                # Front hair base: blend ParamHairFront in center and ParamHairSide on outer sides (3x3 = 9 kfs)
                axes = [("ParamHairFront", SWAY_KEYS), ("ParamHairSide", SWAY_KEYS)]
                kfs = []
                for sv_s in SWAY_KEYS:
                    for sv_f in SWAY_KEYS:
                        pts = rest_xy.copy()
                        w_side = np.array([sstep(sx0, sx1, abs(float(x) - km.HX)) for x in pts[:, 0]])
                        phi = (1.0 - w_side) * (sv_f * 0.12) + w_side * (sv_s * 0.14)
                        phi2 = phi * 1.4
                        t = np.clip((pts[:, 1] - top_y) / max(flen, 1.0), 0.0, 1.15)
                        pts[:, 0] += flen * (phi * 0.7 * (t ** 1.6) + phi2 * 0.5 * (t ** 3))
                        kfs.append((base_op, do, parent_warp.to_local(pts)))
                b.add_art_mesh(mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)
            return

        # Fallback generic hairPart
        pid = "ParamHairBack" if is_back else "ParamHairFront"
        root_y = 560.0 if is_back else float(L["y"])
        hlen = max(60.0, (L["y"] + L["h"] - 560.0) if is_back else float(L["h"]))
        kfs = []
        for sv in SWAY_KEYS:
            phi = sv * 0.20
            phi2 = phi * 1.5
            pts = rest_xy.copy()
            t = np.clip((pts[:, 1] - root_y) / hlen, 0.0, 1.0)
            pts[:, 0] += hlen * (phi * 0.7 * (t ** 1.6) + phi2 * 0.5 * (t ** 3))
            kfs.append((base_op, do, parent_warp.to_local(pts)))
        b.add_art_mesh(mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, [(pid, SWAY_KEYS)], kfs)

    def emit_phys_layer(L: dict) -> None:
        entry = entries.get(L["name"])
        if entry is None:
            return
        pid, spec = phys_by_layer[L["name"]]
        sid = spec["id"]
        parent_warp = phys_parent_warps[sid]
        base_L = km.by_name[spec["layers"][0]]
        part_idx = part_body if spec.get("attach") == "body" else part_head
        cell = 18.0 if spec.get("type") in ("pendulum", "sprout") else 28.0
        rest_xy, uvs, tris = _grid_mesh_for_entry(entry, cell)
        do = next_do()
        base_op = float(L.get("opacity", 1.0))
        max_rad = float(spec.get("max", 0.25))
        mid = _safe_id("Mesh_Phys", L["name"], used_ids)

        kfs = []
        for sv in SWAY_KEYS:
            phi = sv * max_rad
            pts = np.empty_like(rest_xy)
            for vi in range(rest_xy.shape[0]):
                pts[vi, 0], pts[vi, 1] = km.phys_shift(spec, base_L, float(rest_xy[vi, 0]), float(rest_xy[vi, 1]), phi)
            kfs.append((base_op, do, parent_warp.to_local(pts)))
        b.add_art_mesh(mid, part_idx, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, [(pid, SWAY_KEYS)], kfs)

    def emit_brow_layer(L: dict, key: str, over_hair: bool = False) -> None:
        entry = entries.get(L["name"])
        if entry is None:
            return
        parent_warp = warp_brow_over[key] if over_hair else warp_brows[key]
        g_ax, g_ay = model["curves"][f"brow{key}"]
        side = 1.0 if key == "R" else -1.0
        lw = max(10.0, float(L["w"]))
        rest_xy, uvs, tris = _grid_mesh_for_entry(entry, 16.0)
        do = next_do()
        base_op = float(L.get("opacity", 1.0))
        mid = f"Mesh_Brow{key}_Over" if over_hair else f"Mesh_Brow{key}"

        p_y = f"ParamBrow{key}Y"
        p_a = f"ParamBrow{key}Angle"
        p_f = f"ParamBrow{key}Form"
        axes = [(p_y, (-1.0, 0.0, 1.0)), (p_a, (-1.0, 0.0, 1.0)), (p_f, (-1.0, 0.0, 1.0))]
        kfs = []
        for bf in (-1.0, 0.0, 1.0):
            for ba in (-1.0, 0.0, 1.0):
                a = ba * side * 0.3
                ca, sa = math.cos(a), math.sin(a)
                for by_v in (-1.0, 0.0, 1.0):
                    lx = rest_xy[:, 0] - g_ax
                    ly = rest_xy[:, 1] - g_ay
                    bend = -bf * 11.0 * (1.0 - np.minimum(1.0, (lx / (0.5 * lw)) ** 2))
                    pts = np.empty_like(rest_xy)
                    pts[:, 0] = g_ax + lx * ca - ly * sa
                    pts[:, 1] = g_ay + lx * sa + ly * ca - by_v * km.BROW_AMP + bend
                    kfs.append((base_op, do, parent_warp.to_local(pts)))
        b.add_art_mesh(mid, part_brow, parent_warp.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)

    # Precompute KeyEye calibrated open keys & T/B/L curve evaluator (exact port of keyshape.js)
    key_eye_data: dict[str, dict] = {}
    if has_key_eye:
        for key in ("R", "L"):
            ke_raw = model["keyEye"].get(key)
            if not ke_raw or "open" not in ke_raw or "closed" not in ke_raw:
                continue
            ec = model["curves"][f"eye{key}"]
            xa = float(ec["xa"])
            n_col = len(ec["U"])
            K = {
                nm: {
                    "T": np.asarray(v["T"], dtype=np.float64),
                    "B": np.asarray(v["B"], dtype=np.float64),
                    "L": np.asarray(v["L"], dtype=np.float64),
                    "closed": bool(v.get("closed")),
                }
                for nm, v in ke_raw.items()
                if "T" in v
            }
            base_def = [("closed", 0.0), ("o20", 0.2), ("o50", 0.5), ("o70", 0.7), ("open", 1.0), ("wide", 1.2)]
            base_list = [[nm, val] for nm, val in base_def if nm in K]
            i0, i1 = int(math.floor(n_col * 0.25)), int(math.ceil(n_col * 0.75))
            area = lambda nm: float(np.sum(np.maximum(K[nm]["L"][i0:i1] - K[nm]["B"][i0:i1], 0.0)))
            a0 = area("open")
            mid_items = [e for e in base_list if e[0] not in ("closed", "open", "wide")]
            cal = [area(e[0]) / max(a0, 1.0) for e in mid_items]
            if a0 > 1.0 and all(v > 0.03 and v < 0.97 and (idx == 0 or v > cal[idx - 1] + 0.03) for idx, v in enumerate(cal)):
                for item, cv in zip(mid_items, cal):
                    item[1] = cv
            rest_scale = clamp(float(model.get("keyEyeRest", 1.0)), 0.6, 1.0)

            def eval_tbl(o_val: float, s_val: float, K=K, base_list=base_list, rest_scale=rest_scale, n_col=n_col):
                o = clamp(o_val, 0.0, 1.2)
                s = clamp(s_val, 0.0, 1.0) if ("smileClosed" in K and "smileNarrow" in K) else 0.0
                o1 = min(o, 1.0)
                if rest_scale < 1.0:
                    o = o * rest_scale if o <= 1.0 else rest_scale + (o - 1.0) * (1.2 - rest_scale) / 0.2
                wg: dict[str, float] = {}
                # Base weight interpolation
                a_e = b_e = base_list[0]
                t_e = 0.0
                if o >= base_list[-1][1]:
                    a_e = b_e = base_list[-1]
                else:
                    for idx in range(len(base_list) - 1):
                        if base_list[idx][1] <= o <= base_list[idx + 1][1]:
                            a_e = base_list[idx]
                            b_e = base_list[idx + 1]
                            t_e = (o - a_e[1]) / max(b_e[1] - a_e[1], 1e-6)
                            break
                wg[a_e[0]] = wg.get(a_e[0], 0.0) + (1.0 - s) * (1.0 - t_e)
                wg[b_e[0]] = wg.get(b_e[0], 0.0) + (1.0 - s) * t_e
                if s > 0.0:
                    wg["smileClosed"] = wg.get("smileClosed", 0.0) + s * (1.0 - o1)
                    wg["smileNarrow"] = wg.get("smileNarrow", 0.0) + s * o1
                T = np.zeros(n_col, dtype=np.float64)
                B = np.zeros(n_col, dtype=np.float64)
                Lw = np.zeros(n_col, dtype=np.float64)
                for nm, w in wg.items():
                    if w:
                        T += w * K[nm]["T"]
                        B += w * K[nm]["B"]
                        Lw += w * K[nm]["L"]
                swap = Lw < B
                m = 0.5 * (Lw + B)
                Lw = np.where(swap, m, Lw)
                B = np.where(swap, m, B)
                T = np.minimum(T, B - 2.0)
                hgt = Lw - B
                Ut = B - np.minimum(4.0, hgt)
                Lt = np.maximum(Lw + np.minimum(1.5, hgt), Ut)
                ap0 = float(np.sum(np.maximum(K["open"]["L"] - K["open"]["B"], 0.0)))
                apert = float(np.sum(hgt)) / max(ap0, 1.0)
                return T, B, Lw, Ut, Lt, apert

            # Always insert tight switch keys (0.08, 0.12) near closed so closed<->open transitions
            # in a razor-thin 0.04 window instead of ghosting across [0.0, o20] (which can be >0.5 wide!).
            raw_keys = {round(float(v), 4) for _, v in base_list} | {0.0, 0.08, 0.12, 1.0}
            # Remove any key colliding within 0.015 of 0.08 or 0.12 so keys stay cleanly spaced
            open_keys = tuple(sorted(
                v for v in raw_keys
                if v in (0.0, 0.08, 0.12, 1.0) or (abs(v - 0.08) > 0.015 and abs(v - 0.12) > 0.015)
            ))
            key_eye_data[key] = {
                "xa": xa,
                "n": n_col,
                "K": K,
                "open_keys": open_keys,
                "eval_tbl": eval_tbl,
                "U0": np.asarray(ec["U"], dtype=np.float64),
                "L0": np.asarray(ec["L"], dtype=np.float64),
            }

    def emit_sclera(L: dict, key: str) -> int:
        entry = entries[L["name"]]
        ew = warp_eyes[key]
        pidx = part_eye_r if key == "R" else part_eye_l
        rest_xy, uvs, tris = _grid_mesh_for_entry(entry, 12.0)
        do = next_do()
        base_op = float(L.get("opacity", 1.0))
        p_open = f"ParamEye{key}Open"
        p_smile = f"ParamEye{key}Smile"

        if key in key_eye_data:
            kd = key_eye_data[key]
            okeys = kd["open_keys"]
            xa = kd["xa"]
            n_col = kd["n"]
            U0, L0 = kd["U0"], kd["L0"]
            K = kd["K"]

            # Create a tiny WarpDeformer around sclera so sad/glare/jito eyelid curves clip the sclera & iris cleanly!
            expr_sclera_keys = [
                (nm, pid)
                for nm, pid in (("sad", "ParamEyeSad"), ("glare", "ParamEyeGlare"), ("jito", "ParamEyeJito"))
                if nm in K
            ]
            sclera_parent = ew
            if expr_sclera_keys:
                sx0 = float(entry.layer_x + entry.crop_x) - 10.0
                sy0 = float(entry.layer_y + entry.crop_y) - 10.0
                sx1 = float(entry.layer_x + entry.crop_x + entry.crop_w) + 10.0
                sy1 = float(entry.layer_y + entry.crop_y + entry.crop_h) + 10.0
                s_rows, s_cols = 2, 8
                gxs = np.linspace(sx0, sx1, s_cols + 1)
                gys = np.linspace(sy0, sy1, s_rows + 1)
                g_col = np.clip(np.round(gxs - xa).astype(np.int32), 0, n_col - 1)
                open_B = K["open"]["B"][g_col]
                open_L = K["open"]["L"][g_col]
                w_axes = [(pid, (0.0, 1.0)) for _, pid in expr_sclera_keys]
                n_e = len(expr_sclera_keys)
                w_kfs = []
                for mask_bits in range(1 << n_e):
                    # Active expression deltas (summed relative to open curve)
                    dB = np.zeros(s_cols + 1, dtype=np.float64)
                    dL = np.zeros(s_cols + 1, dtype=np.float64)
                    for bi, (nm, _) in enumerate(expr_sclera_keys):
                        if (mask_bits >> bi) & 1:
                            dB += K[nm]["B"][g_col] - open_B
                            dL += K[nm]["L"][g_col] - open_L
                    pts = np.empty((s_rows + 1) * (s_cols + 1) * 2, dtype=np.float32)
                    kk = 0
                    for r_i, gy in enumerate(gys):
                        for c_i, gx in enumerate(gxs):
                            t_r = clamp((float(gy) - float(U0[g_col[c_i]])) / max(float(L0[g_col[c_i]] - U0[g_col[c_i]]), 1.0), 0.0, 1.0)
                            ny = float(gy) + (1.0 - t_r) * float(dB[c_i]) + t_r * float(dL[c_i])
                            pts[kk] = float((gx - ew.x0) / ew.w)
                            pts[kk + 1] = float((ny - ew.y0) / ew.h)
                            kk += 2
                    w_kfs.append((1.0, pts))
                d_sc = b.add_warp_deformer(
                    f"Warp_ScleraExpr{key}", ew.def_idx, pidx, s_rows, s_cols, w_axes, w_kfs, bilinear=1
                )
                sclera_parent = _WarpBox(d_sc, sx0, sy0, sx1, sy1)

            col_i = np.clip(np.round(rest_xy[:, 0] - xa).astype(np.int32), 0, n_col - 1)
            Uy0 = U0[col_i]
            Ly0 = L0[col_i]
            t_col = np.clip((rest_xy[:, 1] - Uy0) / np.maximum(Ly0 - Uy0, 1.0), 0.0, 1.0)
            axes = [(p_open, okeys), (p_smile, (0.0, 1.0))]
            kfs = []
            for sv in (0.0, 1.0):
                for ov in okeys:
                    _, _, _, Ut, Lt, apert = kd["eval_tbl"](ov, sv)
                    dy = (1.0 - t_col) * (Ut[col_i] - Uy0) + t_col * (Lt[col_i] - Ly0)
                    pts = rest_xy.copy()
                    pts[:, 1] += dy
                    op = base_op * sstep(0.09, 0.16, ov) * sstep(0.05, 0.16, apert)
                    kfs.append((op, do, sclera_parent.to_local(pts)))
        else:
            sclera_parent = ew
            axes = [(p_open, (0.0, 1.0))]
            kfs = [(0.0, do, ew.to_local(rest_xy)), (base_op, do, ew.to_local(rest_xy))]

        masks = [face_mask_idx] if face_mask_idx is not None else []
        m_idx = b.add_art_mesh(
            f"Mesh_Sclera{key}", pidx, sclera_parent.def_idx, entry.texture_idx, layer_flags(L),
            uvs, tris, axes, kfs, masks=masks,
        )
        white_mask_idx[key] = m_idx
        return m_idx

    def emit_key_eye(key: str) -> None:
        if key not in key_eye_data:
            return
        kd = key_eye_data[key]
        K = kd["K"]
        xa = kd["xa"]
        n_col = kd["n"]
        okeys = kd["open_keys"]
        ew = warp_eyes[key]
        ew_norm = warp_eye_normal[key]
        pidx = part_eye_r if key == "R" else part_eye_l
        p_open = f"ParamEye{key}Open"
        p_smile = f"ParamEye{key}Smile"
        ROWS = 8

        def build_eye_strip(L: dict, k_ref: dict, f_above: float):
            entry = entries[L["name"]]
            nx = max(6, int(math.ceil(L["w"] / 10.0)))
            nv = (nx + 1) * ROWS
            rest = np.empty((nv, 2), dtype=np.float64)
            col_arr = np.empty(nx + 1, dtype=np.int32)
            tris_list: list[int] = []
            for i in range(nx + 1):
                x = float(L["x"]) + (float(L["w"]) * i) / nx
                j = int(clamp(round(x - xa), 0, n_col - 1))
                col_arr[i] = j
                T0 = float(k_ref["T"][j])
                B0 = max(float(k_ref["B"][j]), T0 + 1.0)
                L0 = max(float(k_ref["L"][j]), B0)
                top = min(float(L["y"]), T0 - 1.0)
                bot = max(float(L["y"] + L["h"]), L0 + 1.0)
                ys = (top, T0, 0.5 * (T0 + B0), B0, B0 + (L0 - B0) / 3.0, B0 + 2.0 * (L0 - B0) / 3.0, L0, bot)
                for r in range(ROWS):
                    v = i * ROWS + r
                    rest[v, 0] = x
                    rest[v, 1] = ys[r]
                    if i < nx and r < ROWS - 1:
                        tris_list.extend((v, v + ROWS, v + 1, v + 1, v + ROWS, v + ROWS + 1))
            u, v_uv = entry.uv_for_model_xy(rest[:, 0], rest[:, 1])
            uvs = np.empty(nv * 2, dtype=np.float32)
            uvs[0::2] = u
            uvs[1::2] = v_uv

            def place_for_tbl(T: np.ndarray, B: np.ndarray, Lw: np.ndarray, dy: float = 0.0) -> np.ndarray:
                pts = rest.copy()
                for i in range(nx + 1):
                    j = int(col_arr[i])
                    Tc = float(T[j])
                    Bc = float(B[j])
                    kT = float(k_ref["T"][j])
                    kB = float(k_ref["B"][j])
                    kL = float(k_ref["L"][j])
                    flat = (kL - kB) < 2.0
                    Lc = Bc if flat else float(Lw[j])
                    v0 = i * ROWS
                    dT = (Tc - kT) * f_above
                    pts[v0 + 0, 1] = rest[v0 + 0, 1] + dT + dy
                    pts[v0 + 1, 1] = kT + dT + dy
                    pts[v0 + 2, 1] = 0.5 * (kT + dT + Bc) + dy
                    pts[v0 + 3, 1] = Bc + dy
                    pts[v0 + 4, 1] = Bc + (Lc - Bc) / 3.0 + dy
                    pts[v0 + 5, 1] = Bc + 2.0 * (Lc - Bc) / 3.0 + dy
                    pts[v0 + 6, 1] = Lc + dy
                    pts[v0 + 7, 1] = rest[v0 + 7, 1] + (Lc - max(kL, max(kB, kT + 1.0))) + dy
                return pts

            return entry, uvs, np.array(tris_list, dtype=np.uint16), place_for_tbl

        # 1. Under / crease / corner layers
        crease_k = model.get("keyEyeCrease")
        if crease_k and f"目キー_crease{key}" in entries and crease_k in K:
            L = km.by_name[f"目キー_crease{key}"]
            entry, uvs, tris, place = build_eye_strip(L, K[crease_k], 0.4)
            do = next_do()
            axes = [(p_open, okeys), (p_smile, (0.0, 1.0))]
            kfs = []
            for sv in (0.0, 1.0):
                for ov in okeys:
                    T, B, Lw, _, _, _ = kd["eval_tbl"](ov, sv)
                    kfs.append((float(L.get("opacity", 1.0)), do, ew.to_local(place(T, B, Lw))))
            b.add_art_mesh(f"Mesh_EyeCrease{key}", pidx, ew.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)

        if f"目キー_under{key}" in entries:
            L = km.by_name[f"目キー_under{key}"]
            entry, uvs, tris, place = build_eye_strip(L, K["open"], 0.4)
            do = next_do()
            axes = [(p_open, okeys), (p_smile, (0.0, 1.0))]
            kfs = []
            for sv in (0.0, 1.0):
                for ov in okeys:
                    T, B, Lw, _, _, _ = kd["eval_tbl"](ov, sv)
                    kfs.append((float(L.get("opacity", 1.0)), do, ew.to_local(place(T, B, Lw))))
            b.add_art_mesh(f"Mesh_EyeUnder{key}", pidx, ew.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)

        if f"目キー_corner{key}" in entries:
            L = km.by_name[f"目キー_corner{key}"]
            entry, uvs, tris, place = build_eye_strip(L, K["open"], 1.0)
            do = next_do()
            axes = [(p_open, okeys), (p_smile, (0.0, 1.0))]
            kfs = []
            for sv in (0.0, 1.0):
                for ov in okeys:
                    T, B, Lw, _, _, apert = kd["eval_tbl"](ov, sv)
                    op = float(L.get("opacity", 1.0)) * sstep(0.62, 0.92, apert)
                    kfs.append((op, do, ew.to_local(place(T, B, Lw))))
            b.add_art_mesh(f"Mesh_EyeCorner{key}", pidx, ew.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)

        # 2. Normal lashes (under Warp_EyeNormal so expression eyes cleanly replace them!)
        # Razor-thin switch windows:
        #   - open <-> closed swaps strictly in [0.08, 0.12] (never stuck half-transparent at 0.15..0.5!)
        #   - normal <-> smile swaps strictly in [0.58, 0.62] (never stuck half-transparent at smile=0.5!)
        smile_keys = (0.0, 0.58, 0.62, 1.0)
        normal_specs = [
            ("open", lambda ov, sv: (1.0 if ov >= 0.11 else 0.0) if sv <= 0.60 else 0.0),
            ("closed", lambda ov, sv: (1.0 if ov < 0.11 else 0.0) if sv <= 0.60 else 0.0),
            ("smileNarrow", lambda ov, sv: (1.0 if ov >= 0.11 else 0.0) if sv > 0.60 else 0.0),
            ("smileClosed", lambda ov, sv: (1.0 if ov < 0.11 else 0.0) if sv > 0.60 else 0.0),
        ]
        # Optional subtle eyelid shadow clipped to sclera (faded out cleanly before closed)
        lid_shadow = model.get("lidShadow")
        if isinstance(lid_shadow, list) and len(lid_shadow) >= 2 and f"目キー_open{key}" in entries and key in white_mask_idx:
            L = km.by_name[f"目キー_open{key}"]
            sh_dy, sh_op = float(lid_shadow[0]), float(lid_shadow[1])
            entry, uvs, tris, place = build_eye_strip(L, K["open"], 1.0)
            do = next_do()
            axes = [(p_open, okeys), (p_smile, (0.0, 1.0))]
            kfs = []
            for sv in (0.0, 1.0):
                for ov in okeys:
                    T, B, Lw, _, _, apert = kd["eval_tbl"](ov, sv)
                    op = sh_op * sstep(0.18, 0.35, ov) * sstep(0.15, 0.30, apert)
                    kfs.append((op, do, ew_norm.to_local(place(T, B, Lw, dy=sh_dy))))
            b.add_art_mesh(
                f"Mesh_LidShadow{key}", pidx, ew_norm.def_idx, entry.texture_idx, 4,
                uvs, tris, axes, kfs, masks=[white_mask_idx[key]],
            )

        for nm, op_fn in normal_specs:
            lname = f"目キー_{nm}{key}"
            if lname not in entries or nm not in K:
                continue
            L = km.by_name[lname]
            entry, uvs, tris, place = build_eye_strip(L, K[nm], 1.0)
            do = next_do()
            axes = [(p_open, okeys), (p_smile, smile_keys)]
            kfs = []
            for sv in smile_keys:
                for ov in okeys:
                    T, B, Lw, _, _, _ = kd["eval_tbl"](ov, sv)
                    kfs.append((float(L.get("opacity", 1.0)) * op_fn(ov, sv), do, ew_norm.to_local(place(T, B, Lw))))
            b.add_art_mesh(f"Mesh_Eye_{nm}_{key}", pidx, ew_norm.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)

        # 3. Expression eye shapes (sad, glare, jito, shut) that still blink smoothly on ParamEyeOpen!
        expr_eye_map = [
            ("sad", "ParamEyeSad"),
            ("glare", "ParamEyeGlare"),
            ("jito", "ParamEyeJito"),
            ("shut", "ParamEyeShut"),
        ]
        for nm, ep_id in expr_eye_map:
            lname = f"目キー_{nm}{key}"
            if lname not in entries or nm not in K:
                continue
            L = km.by_name[lname]
            entry, uvs, tris, place = build_eye_strip(L, K[nm], 1.0)
            do = next_do()
            if nm == "shut":
                pts0 = ew.to_local(place(K["shut"]["T"], K["shut"]["B"], K["shut"]["L"]))
                b.add_art_mesh(
                    f"Mesh_Eye_{nm}_{key}", pidx, ew.def_idx, entry.texture_idx, layer_flags(L),
                    uvs, tris, [(ep_id, (0.0, 1.0))],
                    [(0.0, do, pts0), (float(L.get("opacity", 1.0)), do, pts0)],
                )
            else:
                e_okeys = (0.0, 0.25, 1.0)
                axes = [(p_open, e_okeys), (ep_id, (0.0, 1.0))]
                kfs = []
                for ev in (0.0, 1.0):
                    for ov in e_okeys:
                        # Blend from closed curve (ov=0) to expression curve (ov=1)
                        w = clamp(ov, 0.0, 1.0)
                        T = (1.0 - w) * K["closed"]["T"] + w * K[nm]["T"]
                        B = (1.0 - w) * K["closed"]["B"] + w * K[nm]["B"]
                        Lw = (1.0 - w) * K["closed"]["L"] + w * K[nm]["L"]
                        kfs.append((float(L.get("opacity", 1.0)) * ev, do, ew.to_local(place(T, B, Lw))))
                b.add_art_mesh(f"Mesh_Eye_{nm}_{key}", pidx, ew.def_idx, entry.texture_idx, layer_flags(L), uvs, tris, axes, kfs)

    def emit_key_mouth() -> None:
        if not has_key_mouth:
            return
        km_keys = model["keyMouth"]["keys"]
        if "closed" not in km_keys or "口キー_closed" not in entries:
            return
        NC, MR, PADX, PADY, STROKE = 20, 7, 9.0, 7.0, 6.0

        def get_curve(nm: str) -> tuple[float, float, np.ndarray, np.ndarray]:
            k = km_keys[nm]
            return float(k["xa"]), float(k["xb"]), np.asarray(k["U"], dtype=np.float64), np.asarray(k["Lo"], dtype=np.float64)

        def build_mouth_strip(nm: str):
            L = km.by_name[f"口キー_{nm}"]
            entry = entries[L["name"]]
            xa, xb, U, Lo = get_curve(nm)
            N = U.size
            cols = NC + 3
            nv = cols * MR
            rest = np.empty((nv, 2), dtype=np.float64)
            uu = np.empty(cols, dtype=np.float64)
            tris_list: list[int] = []
            for c in range(cols):
                u = clamp((c - 1) / NC, 0.0, 1.0)
                f = u * (N - 1)
                i0 = min(int(math.floor(f)), N - 2)
                t = f - i0
                x = (xa - PADX) if c == 0 else ((xb + PADX) if c == cols - 1 else (xa + (xb - xa) * u))
                Uy = lerp(float(U[i0]), float(U[i0 + 1]), t)
                Ly = max(lerp(float(Lo[i0]), float(Lo[i0 + 1]), t), Uy + 1.0)
                sw = min(STROKE, 0.5 * (Ly - Uy))
                ys = (Uy - PADY, Uy, Uy + sw, 0.5 * (Uy + Ly), Ly - sw, Ly, Ly + PADY)
                uu[c] = -1.0 if c == 0 else (2.0 if c == cols - 1 else u)
                for r in range(MR):
                    v = c * MR + r
                    rest[v, 0] = x
                    rest[v, 1] = ys[r]
                    if c < cols - 1 and r < MR - 1:
                        tris_list.extend((v, v + MR, v + 1, v + 1, v + MR, v + MR + 1))
            u_arr, v_arr = entry.uv_for_model_xy(rest[:, 0], rest[:, 1])
            uvs = np.empty(nv * 2, dtype=np.float32)
            uvs[0::2] = u_arr
            uvs[1::2] = v_arr

            def place_curve(c_xa: float, c_xb: float, c_U: np.ndarray, c_Lo: np.ndarray) -> np.ndarray:
                pts = np.empty((nv, 2), dtype=np.float64)
                N_c = c_U.size
                for c in range(cols):
                    u = clamp(float(uu[c]), 0.0, 1.0)
                    f = u * (N_c - 1)
                    i0 = min(int(math.floor(f)), N_c - 2)
                    t = f - i0
                    x = (c_xa - PADX) if uu[c] < 0 else ((c_xb + PADX) if uu[c] > 1 else (c_xa + (c_xb - c_xa) * u))
                    Uy = lerp(float(c_U[i0]), float(c_U[i0 + 1]), t)
                    Ly = max(lerp(float(c_Lo[i0]), float(c_Lo[i0 + 1]), t), Uy + 1.0)
                    sw = min(STROKE, 0.5 * (Ly - Uy))
                    ys = (Uy - PADY, Uy, Uy + sw, 0.5 * (Uy + Ly), Ly - sw, Ly, Ly + PADY)
                    for r in range(MR):
                        v = c * MR + r
                        pts[v, 0] = x
                        pts[v, 1] = ys[r]
                return pts

            return L, entry, uvs, np.array(tris_list, dtype=np.uint16), place_curve

        def pick(candidates: list[str]) -> str:
            for c in candidates:
                if c in km_keys and f"口キー_{c}" in entries:
                    return c
            return "closed"

        # 4x3 tracking grid: (ParamMouthOpenY, ParamMouthForm)
        m_open_keys = (0.0, 0.25, 0.6, 1.0)
        m_form_keys = (-1.0, 0.0, 1.0)
        # Grid mapping (open_idx, form_idx) -> (source_key_name, smile_corner_lift_px, open_scale_y)
        grid_choice: dict[tuple[int, int], tuple[str, float, float]] = {
            (0, 0): (pick(["he", "closed"]), 0.0, 1.0),
            (0, 1): ("closed", 0.0, 1.0),
            (0, 2): ("closed", -9.0, 1.0),
            (1, 0): (pick(["u", "small", "a"]), 0.0, 1.0),
            (1, 1): (pick(["small", "a"]), 0.0, 1.0),
            (1, 2): (pick(["i", "small", "a"]), 0.0, 1.0),
            (2, 0): (pick(["o", "u", "a"]), 0.0, 1.0),
            (2, 1): (pick(["a", "small"]), 0.0, 1.0),
            (2, 2): (pick(["e", "laugh", "a"]), 0.0, 1.0),
            (3, 0): (pick(["o", "a"]), 0.0, 1.12),
            (3, 1): (pick(["a", "laugh"]), 0.0, 1.15),
            (3, 2): (pick(["laugh", "a"]), 0.0, 1.05),
        }

        # Precompute target curve at each (oi, fi)
        grid_curves: dict[tuple[int, int], tuple[float, float, np.ndarray, np.ndarray]] = {}
        used_normal_shapes: list[str] = []
        for (oi, fi), (sk, lift_px, sy) in grid_choice.items():
            if sk not in used_normal_shapes:
                used_normal_shapes.append(sk)
            xa, xb, U, Lo = get_curve(sk)
            U = U.copy()
            Lo = Lo.copy()
            if lift_px != 0.0:
                u_lin = np.linspace(-1.0, 1.0, U.size)
                # Lift corners (|u| near 1) smoothly for smiling closed mouth
                dy = lift_px * (u_lin ** 2)
                U += dy
                Lo += dy
            if sy != 1.0:
                mid = 0.5 * (U + Lo)
                U = mid + (U - mid) * sy
                Lo = mid + (Lo - mid) * sy
            grid_curves[(oi, fi)] = (xa, xb, U, Lo)

        masks = [face_mask_idx] if face_mask_idx is not None else []
        axes = [("ParamMouthOpenY", m_open_keys), ("ParamMouthForm", m_form_keys)]

        for sk in used_normal_shapes:
            L, entry, uvs, tris, place = build_mouth_strip(sk)
            do = next_do()
            base_op = float(L.get("opacity", 1.0))
            kfs = []
            for fi in range(len(m_form_keys)):
                for oi in range(len(m_open_keys)):
                    c_xa, c_xb, c_U, c_Lo = grid_curves[(oi, fi)]
                    active = 1.0 if grid_choice[(oi, fi)][0] == sk else 0.0
                    kfs.append((base_op * active, do, warp_mouth_normal.to_local(place(c_xa, c_xb, c_U, c_Lo))))
            b.add_art_mesh(
                f"Mesh_Mouth_{sk}", part_mouth, warp_mouth_normal.def_idx, entry.texture_idx,
                layer_flags(L), uvs, tris, axes, kfs, masks=masks,
            )

        # Expression override mouth shapes (directly under warp_mouth)
        for mk in expr_mouth_keys:
            mpid = f"ParamMouthExpr_{mk}"
            if mk not in km_keys or f"口キー_{mk}" not in entries:
                continue
            L, entry, uvs, tris, place = build_mouth_strip(mk)
            do = next_do()
            base_op = float(L.get("opacity", 1.0))
            xa, xb, U, Lo = get_curve(mk)
            pts_local = warp_mouth.to_local(place(xa, xb, U, Lo))
            b.add_art_mesh(
                f"Mesh_MouthExpr_{mk}", part_mouth, warp_mouth.def_idx, entry.texture_idx,
                layer_flags(L), uvs, tris, [(mpid, (0.0, 1.0))],
                [(0.0, do, pts_local), (base_op, do, pts_local)],
                masks=masks,
            )

    # 10. Walk layers in exact avatar.js order!
    diff_layers = [L for L in needed_layers if L["path"].startswith("表情差分")]
    iris_diff_layers = {
        "R": [L for L in diff_layers if re.search(r"ハート|しいたけ|ぐるぐる|闇", L["name"]) and (L["x"] + L["w"] * 0.5) < km.HX],
        "L": [L for L in diff_layers if re.search(r"ハート|しいたけ|ぐるぐる|闇", L["name"]) and (L["x"] + L["w"] * 0.5) >= km.HX],
    }
    face_diff_layers = [L for L in diff_layers if not re.search(r"ハート|しいたけ|ぐるぐる|闇", L["name"])]

    def emit_diff_layer(L: dict) -> None:
        key = re.sub(r"[RL]$", "", L["name"])
        dpid = DIFF_PARAM_MAP.get(key)
        if not dpid:
            return
        if re.search(r"ハート|しいたけ|ぐるぐる|闇", L["name"]):
            side = "R" if (L["x"] + L["w"] * 0.5) < km.HX else "L"
            emit_simple_layer(L, warp_iris[side], part_expr, cell=12.0, clip_eye=side, diff_param=dpid)
        elif (model.get("diffAttach") or {}).get(key) == "eye" and warp_eye_follow is not None:
            emit_simple_layer(L, warp_eye_follow, part_expr, cell=20.0, clip_face=False, diff_param=dpid)
        else:
            clip_f = not bool(re.search(r"汗|涙", L["name"]))
            w_parent = warp_face_shade if clip_f else warp_face_skin
            emit_simple_layer(L, w_parent, part_expr, cell=24.0, clip_face=clip_f, diff_param=dpid)

    mouth_done = False
    diff_done = False
    key_eye_done: set[str] = set()
    brow_layers_seen: list[tuple[dict, str]] = []
    iris_diffs_emitted: set[str] = set()

    for L in needed_layers:
        ln = L["name"]
        lp = L["path"]
        if lp.startswith("表情差分"):
            continue
        if ln.startswith("目キー_"):
            ek = "R" if ln.endswith("R") else "L"
            if ek not in key_eye_done:
                key_eye_done.add(ek)
                # Ensure iris diffs for this eye are drawn BEFORE eyelashes
                if ek not in iris_diffs_emitted:
                    iris_diffs_emitted.add(ek)
                    for dL in iris_diff_layers[ek]:
                        emit_diff_layer(dL)
                emit_key_eye(ek)
            continue
        if lp.startswith("頭/顔/口"):
            if not mouth_done:
                mouth_done = True
                emit_key_mouth()
            continue
        if lp == "頭/前髪" and not diff_done:
            diff_done = True
            for dL in face_diff_layers:
                emit_diff_layer(dL)

        # Dispatch by layer classification (mirroring avatar.js classify())
        if ln in phys_by_layer:
            emit_phys_layer(L)
        elif ln in (model.get("eyeAttach") or []) and warp_eye_follow is not None:
            emit_simple_layer(L, warp_eye_follow, part_face, cell=20.0, clip_face=True)
        elif ln in rigid_pin_warps:
            emit_simple_layer(L, rigid_pin_warps[ln], part_head, cell=36.0)
        elif lp in ("後ろ髪", "結び髪", "頭/前髪"):
            emit_hair_layer(L)
        elif lp.startswith("カーディガン") or lp.startswith("上半身") or ln == "首":
            emit_simple_layer(L, warp_body, part_body, cell=48.0)
        elif lp == "頭/耳" and warp_ear is not None:
            emit_simple_layer(L, warp_ear, part_head, cell=24.0)
        elif lp == "頭/顔/輪郭":
            is_base = ln in ("輪郭ベース", "輪郭線")
            w_p = warp_face_skin if is_base else (warp_face_shade if ln == "頬" else warp_face_skin)
            m_i = emit_simple_layer(L, w_p, part_face, cell=24.0, clip_face=not is_base)
            if ln == "輪郭ベース" and m_i is not None:
                face_mask_idx = m_i
                for dm in deferred_face_clips:
                    b.set_mesh_masks(dm, [face_mask_idx])
                deferred_face_clips.clear()
        elif lp == "頭/顔/輪郭/前髪影":
            emit_simple_layer(L, warp_front_hair, part_face, cell=32.0, clip_face=True)
        elif lp == "頭/顔/鼻":
            emit_simple_layer(L, warp_nose, part_face, cell=10.0)
        elif lp == "頭/顔":
            emit_simple_layer(L, warp_face_skin, part_face, cell=24.0)
        elif lp.startswith("頭/顔/瞳R") or lp.startswith("頭/顔/瞳L"):
            ek = "R" if lp.startswith("頭/顔/瞳R") else "L"
            pidx = part_eye_r if ek == "R" else part_eye_l
            if ln.startswith("白目"):
                emit_sclera(L, ek)
            elif re.search(r"瞳ベース|瞳孔|^ハイライト", ln):
                emit_simple_layer(L, warp_iris[ek], pidx, cell=10.0, clip_eye=ek)
                if ln == f"ハイライト1{ek}" and ek not in iris_diffs_emitted:
                    iris_diffs_emitted.add(ek)
                    for dL in iris_diff_layers[ek]:
                        emit_diff_layer(dL)
            else:
                emit_simple_layer(L, warp_eyes[ek], pidx, cell=16.0, clip_face=True)
        elif lp == "頭/顔/眉毛":
            bk = "R" if ln.endswith("R") else "L"
            emit_brow_layer(L, bk, over_hair=False)
            brow_layers_seen.append((L, bk))
        elif lp == "頭/帽子" and warp_hat is not None:
            emit_simple_layer(L, warp_hat, part_head, cell=36.0)
        elif lp == "頭/ピン留め":
            w_pin = warp_face_skin if model.get("pinAttach") == "skin" else make_head_xy_warp(
                _safe_id("Warp_PinLegacy", ln, used_ids), part_head, *bbox_of([ln], pad=60.0), 4, 4,
                lambda x, y, pose: km.group_apply(km.pin_group_spec, x, y, pose),
            )
            emit_simple_layer(L, w_pin, part_head, cell=28.0)

    if not diff_done:
        for dL in face_diff_layers:
            emit_diff_layer(dL)

    # Hair-over eyebrows (shown when ParamBrowShow > 0)
    for bL, bk in brow_layers_seen:
        emit_brow_layer(bL, bk, over_hair=True)

    # 11. Build and write .moc3
    moc_bytes = b.build(version=moc_version)
    moc_filename = f"{name}.moc3"
    (out_dir / moc_filename).write_bytes(moc_bytes)

    # 12. Write .physics3.json
    phys_filename = f"{name}.physics3.json"
    phys_json = build_physics3(model, phys_specs_list)
    (out_dir / phys_filename).write_text(json.dumps(phys_json, indent=2, ensure_ascii=False), encoding="utf-8")

    # 13. Write expressions/*.exp3.json
    available_params = {p.id for p in b.params}
    expr_map = build_expressions(model, available_params, phys_specs_list)
    expr_dir = out_dir / "expressions"
    expr_dir.mkdir(parents=True, exist_ok=True)
    expr_refs: list[dict] = []
    for slug, ej in expr_map.items():
        ef = f"expressions/{slug}.exp3.json"
        (out_dir / ef).write_text(json.dumps(ej, indent=2, ensure_ascii=False), encoding="utf-8")
        expr_refs.append({"Name": slug, "File": ef})

    # 14. Write .cdi3.json
    cdi_filename = f"{name}.cdi3.json"
    cdi_json = {
        "Version": 3,
        "Parameters": cdi_params,
        "ParameterGroups": [
            {"Id": "GroupHead", "GroupId": "", "Name": "Head"},
            {"Id": "GroupBody", "GroupId": "", "Name": "Body"},
            {"Id": "GroupEye", "GroupId": "", "Name": "Eyes"},
            {"Id": "GroupBrow", "GroupId": "", "Name": "Eyebrows"},
            {"Id": "GroupMouth", "GroupId": "", "Name": "Mouth"},
            {"Id": "GroupPhysics", "GroupId": "", "Name": "Physics"},
            {"Id": "GroupExpr", "GroupId": "", "Name": "Expressions"},
        ],
        "Parts": cdi_parts,
    }
    (out_dir / cdi_filename).write_text(json.dumps(cdi_json, indent=2, ensure_ascii=False), encoding="utf-8")

    # 15. Write .model3.json
    model3_filename = f"{name}.model3.json"
    model3_json = {
        "Version": 3,
        "FileReferences": {
            "Moc": moc_filename,
            "Textures": tex_rel_paths,
            "Physics": phys_filename,
            "DisplayInfo": cdi_filename,
            "Expressions": expr_refs,
        },
        "Groups": [
            {
                "Target": "Parameter",
                "Name": "EyeBlink",
                "Ids": ["ParamEyeLOpen", "ParamEyeROpen"],
            },
            {
                "Target": "Parameter",
                "Name": "LipSync",
                "Ids": ["ParamMouthOpenY"],
            },
        ],
    }
    (out_dir / model3_filename).write_text(json.dumps(model3_json, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "name": name,
        "out_dir": str(out_dir),
        "model3": str(out_dir / model3_filename),
        "moc3": str(out_dir / moc_filename),
        "moc_bytes": len(moc_bytes),
        "textures": tex_rel_paths,
        "parts": len(b.parts),
        "deformers": len(b.deformers),
        "art_meshes": len(b.meshes),
        "parameters": len(b.params),
        "expressions": len(expr_refs),
        "physics_settings": len(phys_json["PhysicsSettings"]),
    }
