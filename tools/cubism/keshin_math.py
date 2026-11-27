"""Faithful Python port of Keshin2D's deformation mathematics (avatar.js & keyshape.js).

Every deformation in Keshin2D operates in canonical 3000-wide model pixel coordinates
(y-down, face center x≈1500, head top y≈111, chin y≈1167, head roll pivot PIV=(1500, 1140)).
This module evaluates those exact formulas cleanly at any pose/parameter tuple so our
Cubism converter can bake them directly onto Live2D WarpDeformers and ArtMesh keyforms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

DEG = math.pi / 180.0
EDGE_BAND = 44.0
PY = 820.0
PIV = (1500.0, 1140.0)
TILT_K = 0.6


def clamp(v: float, a: float, b: float) -> float:
    return a if v < a else (b if v > b else v)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def sstep(a: float, b: float, v: float) -> float:
    if b == a:
        return 0.0 if v < a else 1.0
    t = clamp((v - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def make_knots(pts: list[tuple[float, float]]) -> Callable[[float], float]:
    def fn(y: float) -> float:
        if y <= pts[0][0]:
            return pts[0][1]
        for i in range(1, len(pts)):
            if y <= pts[i][0]:
                return lerp(pts[i - 1][1], pts[i][1], sstep(pts[i - 1][0], pts[i][0], y))
        return pts[-1][1]
    return fn


@dataclass
class Pose:
    sinY: float = 0.0
    cosY: float = 1.0
    sinP: float = 0.0
    cosP: float = 1.0
    sr: float = 0.0
    cr: float = 1.0
    ox: float = 0.0
    oy: float = 0.0
    down: float = 0.0
    tiltT: float = 0.0


@dataclass
class Surface:
    R: Callable[[float], float]
    Zc: Callable[[float], float]
    Z0: Callable[[float], float]
    band: float
    k: float
    bulge: Callable[[float], float]
    Z0P: Optional[Callable[[float], float]] = None
    Z0D: Optional[Callable[[float], float]] = None
    Z0D2: Optional[Callable[[float], float]] = None
    ZP: Optional[Callable[[float, Pose], float]] = None
    crown: bool = False


class KeshinMath:
    """Evaluates Keshin2D's exact per-model deformation functions from model.json."""

    def __init__(self, model: dict) -> None:
        self.model = model
        self.layers = model["layers"]
        self.by_name = {L["name"]: L for L in self.layers}

        # Default tune values from avatar.js TUNE
        self.tune = {
            "yawMax": 20.0,
            "upMax": 5.0,
            "downMax": 5.0,
            "rollMax": 18.0,
            "depth": 1.0,
            "sway": 1.5,
            "solid": 1.0,
            "faceFit": 0.0,
            "mouthFit": 0.0,
            "mouthDownSize": 0.0,
            "mouthPitchBend": 0.0,
            "eyeFit": 0.0,
            "headTilt": 0.0,
            "faceDown": 0.0,
            "turn": 1.0,
            "strand": 1.0,
            "fluff": 1.0,
            "exprLive": 1.0,
            "link": 1.0,
            "browBounce": 0.0,
            "bodyMove": 1.0,
            "lash": 0.0,
        }
        for k, v in (model.get("tune") or {}).items():
            if isinstance(v, (int, float)):
                self.tune[k] = float(v)

        face = model["curves"]["face"]
        self.HX = float(face["cx"])
        self.FACE_TOP = float(face["y0"])
        self.FACE_R = [float(v) for v in face["R"]]
        self.FACE_H = len(self.FACE_R)
        self.R0 = max(self.FACE_R)
        self.TILT_Y0 = self.FACE_TOP + self.FACE_H - 1.0
        self.BODY_BOTTOM = float(model.get("yMax", 3600))
        self.NECK_COMPLETE = bool((model.get("neck") or {}).get("complete", False))
        self.BROW_AMP = float(model.get("browAmp", 16.0))
        self.HAIR_WRAP = clamp(float(model.get("hairWrap", 0.0)), 0.0, 1.0)

        self.FD = {"a": 0.5, "b": 0.72, "k": 0.8, "g": 0.14, "s": 0.25}
        self.PITCH = {"top": 0.0, "upK": 1.3, "downK": 1.35, "chinUp": 0.35}
        self.FIT_Z = 0.75 * self.R0
        self.MOUTH_ROUND = 0.75 * self.R0
        self.EYE_XZ = 0.154 * self.R0
        self.MOUTH_LEAD_FIT = 0.077

        self._build_surfaces()
        self._build_groups()

    def _build_surfaces(self) -> None:
        R0 = self.R0
        face_r = self.FACE_R
        face_top = self.FACE_TOP
        n_r = len(face_r)

        def skin_r(y: float) -> float:
            f = clamp(y - face_top, 0.0, n_r - 1.0)
            i = min(int(math.floor(f)), n_r - 2)
            return max(lerp(face_r[i], face_r[i + 1], f - i) - EDGE_BAND, 6.0)

        zc_skin = make_knots([
            (111.0, 0.0), (300.0, 0.8 * R0), (582.0, 1.02 * R0),
            (820.0, 0.98 * R0), (945.0, 1.15 * R0), (1020.0, 1.0 * R0),
            (1167.0, 0.8 * R0),
        ])
        z0_skin = lambda y: 0.8 * R0 * (clamp((y - 880.0) / 287.0, 0.0, 1.0) ** 1.3)
        z0p_skin = make_knots([
            (586.0, 0.0), (745.0, -0.32 * R0), (871.0, -0.40 * R0),
            (1019.0, 0.0), (1167.0, self.PITCH["chinUp"] * R0),
        ])
        z0d_skin = make_knots([
            (745.0, 0.0), (880.0, 0.1 * R0), (980.0, 0.85 * R0), (1167.0, 0.95 * R0),
        ])
        z0d2_skin = make_knots([
            (600.0, 0.0), (745.0, self.FD["a"] * R0), (880.0, self.FD["b"] * R0),
            (980.0, 0.85 * R0), (1167.0, 0.95 * R0),
        ])
        bulge_skin = lambda y: 0.17 + 0.1 * math.exp(-(((y - 960.0) / 170.0) ** 2))

        self.SKIN = Surface(
            R=skin_r, Zc=zc_skin, Z0=z0_skin,
            band=EDGE_BAND, k=1.0, bulge=bulge_skin,
            Z0P=z0p_skin, Z0D=z0d_skin, Z0D2=z0d2_skin, crown=True,
        )
        self.SHADE = Surface(
            R=skin_r, Zc=zc_skin, Z0=z0_skin,
            band=EDGE_BAND, k=1.0, bulge=bulge_skin,
            Z0P=lambda y: 0.85 * zc_skin(y), Z0D=None, Z0D2=None, crown=True,
        )

        def crown(r: float) -> Callable[[float], float]:
            return lambda y: r * math.sqrt(max(0.04, 1.0 - ((300.0 - y) / 262.0) ** 2)) if y < 300.0 else r

        def shell(r: float, zc: float, k: float) -> Surface:
            return Surface(
                R=crown(r),
                Zc=lambda y: zc * R0 * sstep(40.0, 420.0, y),
                Z0=lambda y: 0.0,
                band=0.0,
                k=k,
                bulge=lambda y: 0.1,
            )

        # Hat dome support (e.g. kurage02)
        hat_layers = [L for L in self.layers if L["path"] == "頭/帽子"]
        hat_parts = self.model.get("hatParts")
        hat_box = None
        if hat_layers:
            if isinstance(hat_parts, list) and len(hat_layers) >= 2:
                b = [L for L in hat_layers if L["name"] == "帽子" or L["name"] in hat_parts]
                if len(b) >= 2:
                    y0 = min(L["y"] for L in b)
                    y1 = max(L["y"] + L["h"] for L in b)
                    hat_box = (y0, y1 - y0)
            if hat_box is None:
                hat_box = (hat_layers[0]["y"], hat_layers[0]["h"])

        hd_raw = self.model.get("hatDome")
        hd = None
        if hd_raw and hat_box is not None:
            d = {} if hd_raw is True else (hd_raw if isinstance(hd_raw, dict) else {})
            hd = {
                "top": float(d.get("top", 0.12)),
                "brim": float(d.get("brim", 1.0)),
                "upTop": float(d.get("upTop", 0.6)),
                "upBrim": float(d.get("upBrim", 0.95)),
                "yawTop": float(d.get("yawTop", 0.3)),
                "yawBrim": float(d.get("yawBrim", 0.78)),
                "p": float(d.get("p", 1.8)),
                "y0": float(hat_box[0]),
                "h": max(1.0, float(hat_box[1]) * float(d.get("at", 0.75))),
            }

        if hd is not None:
            def hd_f(y: float) -> float:
                return 1.0 - ((1.0 - clamp((y - hd["y0"]) / hd["h"], 0.0, 1.0)) ** hd["p"])

            hat_surf = Surface(
                R=lambda y: 960.0,
                Zc=lambda y: lerp(hd["yawTop"], hd["yawBrim"], hd_f(y)) * R0,
                Z0=lambda y: 0.0,
                band=0.0,
                k=1.0,
                bulge=lambda y: 0.05,
                ZP=lambda y, pose: lerp(
                    lerp(hd["top"], hd["brim"], hd_f(y)),
                    lerp(hd["upTop"], hd["upBrim"], hd_f(y)),
                    sstep(-0.07, 0.07, pose.sinP),
                ) * R0,
            )
        else:
            hat_surf = Surface(
                R=lambda y: 960.0,
                Zc=lambda y: 0.50 * R0,
                Z0=lambda y: 0.0,
                band=0.0,
                k=1.0,
                bulge=lambda y: 0.05,
            )

        self.SHELL = {
            "bangs": shell(440.0, 1.1, 1.0),
            "side": shell(508.0, 1.1, 0.2),
            "cap": shell(508.0, -0.1, 1.0),
            "back1": shell(508.0, -0.3, 1.0),
            "back2": shell(508.0, -0.5, 1.0),
            "bun": shell(508.0, -0.25, 1.0),
            "clumpFront": Surface(
                R=lambda y: 640.0,
                Zc=lambda y: lerp(0.55, 0.90, sstep(40.0, 620.0, y)) * R0,
                Z0=lambda y: 0.0, band=0.0, k=1.0, bulge=lambda y: 0.08,
            ),
            "clumpBack": Surface(
                R=lambda y: 680.0,
                Zc=lambda y: lerp(-0.22, -0.46, sstep(40.0, 620.0, y)) * R0,
                Z0=lambda y: 0.0, band=0.0, k=1.0, bulge=lambda y: 0.08,
            ),
            "hat": hat_surf,
        }

    def _build_groups(self) -> None:
        curves = self.model["curves"]
        R0 = self.R0
        self.eye_group_spec = {
            "R": (curves["eyeR"]["iris"][0], curves["eyeR"]["iris"][1], 0.65 * R0, 0.55, 0.75 * R0, {"xz": self.EYE_XZ}),
            "L": (curves["eyeL"]["iris"][0], curves["eyeL"]["iris"][1], 0.65 * R0, 0.55, 0.75 * R0, {"xz": self.EYE_XZ}),
        }
        self.brow_group_spec = {
            "R": (curves["browR"][0], curves["browR"][1], 0.94 * R0, 0.5, 0.0, {"xz": self.EYE_XZ}),
            "L": (curves["browL"][0], curves["browL"][1], 0.94 * R0, 0.5, 0.0, {"xz": self.EYE_XZ}),
        }
        mc = curves["mouth"]
        mcx = (mc["xa"] + mc["xb"]) / 2.0
        mhw0 = (mc["xb"] - mc["xa"]) / 2.0
        myc0 = (mc["Y"][0] + mc["Y"][-1]) / 2.0
        self.mouth_group_spec = (
            mcx, myc0, 0.92 * R0, 0.0, 0.0,
            {
                "lead": 0.2,
                "leadFit": self.MOUTH_LEAD_FIT,
                "asym": 1.0,
                "aw": mhw0 * 0.5,
                "fit": [self.FIT_Z, self.FIT_Z],
                "round": self.MOUTH_ROUND,
                "mouthPitch": mhw0,
            },
        )
        nose_l = next((L for L in self.layers if L["path"] == "頭/顔/鼻"), None)
        na = self.model.get("noseAxis")
        nose_ax0 = clamp(self.HX, nose_l["x"], nose_l["x"] + nose_l["w"]) if nose_l else self.HX
        nose_opt: dict = {
            "lead": 0.1,
            "asym": 1.85,
            "aw": 8.0,
            "fit": [self.FIT_Z, self.FIT_Z],
            "px": na[0] if isinstance(na, list) else (float(na) if isinstance(na, (int, float)) else nose_ax0),
        }
        if isinstance(na, list) and len(na) > 1:
            nose_opt["pxR"] = float(na[1])
        self.nose_group_spec = (1500.0, 940.0, 1.25 * R0, 0.0, 0.0, nose_opt)
        self.pin_group_spec = (1840.0, 535.0, self.SHELL["bangs"], 0.5, 0.0, {})

    def make_pose(self, angle_x: float, angle_y: float) -> Pose:
        """Convert Cubism ParamAngleX/ParamAngleY (both in [-30, 30]) into Keshin2D Pose (no roll/body).

        Applies smooth elliptical corner softening when both X and Y are large simultaneously
        (e.g. webcam trackers hitting (±30, ±30) corners) so cardinal axes keep full range while
        diagonal extremes stay inside the distortion-free 3D envelope.
        """
        nx = clamp(angle_x / 30.0, -1.0, 1.0)
        ny = clamp(angle_y / 30.0, -1.0, 1.0)
        # Squircle corner softening: 1.0 on cardinal axes (nx=0 or ny=0), ~0.76 at (±1, ±1) corners
        corner_scale = 1.0 / (1.0 + 0.32 * (nx * nx) * (ny * ny))
        nx_e = nx * corner_scale
        ny_e = ny * corner_scale

        yaw_max = min(self.tune["yawMax"], 26.0)
        up_max = min(self.tune["upMax"], 14.0)
        down_max = min(self.tune["downMax"], 21.0)

        yaw = nx_e * yaw_max * DEG
        pitch = ny_e * (up_max if ny_e > 0.0 else down_max) * DEG
        sinY = math.sin(yaw)
        cosY = math.cos(yaw)
        sinP = math.sin(pitch)
        cosP = math.cos(pitch)
        down = clamp((-ny_e) * down_max / 31.0, 0.0, 1.0)
        # Moderate diagonal shear so extreme X+Y doesn't skew the face into a parallelogram
        tiltT = self.tune["headTilt"] * (TILT_K * 0.55) * sinP * sinY
        return Pose(sinY=sinY, cosY=cosY, sinP=sinP, cosP=cosP, down=down, tiltT=tiltT)

    def pitch_y(self, y: float, z1: float, pose: Pose) -> float:
        if pose.down > 0.0 and z1 < 0.0:
            z1 = 0.0
        top_drop = pose.down * self.PITCH["top"] * self.FACE_H * (
            1.0 - sstep(self.FACE_TOP, self.FACE_TOP + 0.3 * self.FACE_H, y)
        )
        return PY + (y - PY) * pose.cosP - z1 * pose.sinP + top_drop

    def surf_map(self, S: Surface, x: float, y: float, pose: Pose) -> tuple[float, float]:
        R = S.R(y)
        dx = x - self.HX
        u = clamp(dx / R, -1.0, 1.0)
        over = dx - u * R
        sY = pose.sinY
        a_s = abs(sY)
        sg = -1.0 if sY < 0.0 else 1.0
        us = u * sg
        depth = self.tune["depth"]
        z0 = S.Z0(y) * S.k * depth
        A = (S.Zc(y) - S.Z0(y)) * S.k * depth
        lim = min((0.8 * R) / (1.5 * max(a_s, 1e-4)), 1.2 * R)
        if A > lim:
            A = lim
        elif A < -lim:
            A = -lim
        bell = 1.0 - (abs(u) ** 1.5)
        z = z0 + A * bell
        near = ((1.0 - us) / 2.0) ** 1.5
        far = ((1.0 + us) / 2.0) ** 2
        zP = z
        fdG = 0.0
        if S.Z0P is not None:
            e = S.Z0D(y) if (pose.down > 0.0 and S.Z0D is not None) else S.Z0P(y)
            fd = self.tune["faceDown"]
            if fd > 0.0 and pose.down > 0.0 and S.Z0D is not None and S.Z0D2 is not None:
                fw = sstep(600.0, 760.0, y) * (1.0 - sstep(980.0, 1120.0, y)) * far
                asF = 0.5 * math.tanh(a_s / self.FD["s"]) / math.tanh(0.5 / self.FD["s"])
                e = lerp(e, S.Z0D2(y), min(fd, 1.0)) + fd * self.FD["k"] * self.R0 * asF * fw
                fdG = fd * self.FD["g"] * (-pose.sinP) * fw * asF
            e *= depth
            Ap = clamp(S.Zc(y) * depth - e, -1.2 * R, max(1.2 * R, A))
            zP = e + Ap * bell
        if S.ZP is not None:
            zP = S.ZP(y, pose) * S.k * depth * bell
        topW = (
            1.0 - sstep(self.FACE_TOP + 0.06 * self.FACE_H, self.FACE_TOP + 0.41 * self.FACE_H, y)
            if S.crown
            else 0.0
        )
        crownX = sg * a_s * self.R0 * topW * 0.2
        ox = (
            self.HX + u * R + over + z * sY
            + sg * (R + S.band) * ((1.0 - pose.cosY) * near + S.bulge(y) * a_s * far * (1.0 - topW) + fdG * (1.0 - topW))
            + crownX
            + pose.tiltT * (y - self.TILT_Y0)
        )
        oy = self.pitch_y(y, zP * pose.cosY, pose)
        return ox, oy

    def rot_map(self, x: float, y: float, z: float, pose: Pose) -> tuple[float, float]:
        dx = x - self.HX
        ox = self.HX + dx * pose.cosY + z * pose.sinY + pose.tiltT * (y - self.TILT_Y0)
        oy = self.pitch_y(y, z * pose.cosY * (self.PITCH["upK"] if pose.sinP > 0 else self.PITCH["downK"]), pose)
        return ox, oy

    def ear_deform(self, x: float, y: float, pose: Pose) -> tuple[float, float]:
        sgn = -1.0 if x < self.HX else 1.0
        Rf = self.SKIN.R(y) + EDGE_BAND
        xe = self.HX + sgn * Rf
        tx, _ = self.surf_map(self.SKIN, xe, y, pose)
        tl = pose.tiltT * (y - self.TILT_Y0)
        D = tx - xe - tl
        a_s = abs(pose.sinY)
        if sgn * pose.sinY > 0.0:
            ox = x + D - sgn * 150.0 * clamp(a_s / 0.42, 0.0, 1.0) + tl
        else:
            ox = x + D * lerp(1.0, 0.25, clamp((abs(x - self.HX) - Rf) / 80.0, 0.0, 1.0)) + tl
        oy = self.pitch_y(y, -0.79 * self.R0 * pose.cosY, pose)
        return ox, oy

    def group_apply(
        self,
        spec: tuple,
        x: float,
        y: float,
        pose: Pose,
    ) -> tuple[float, float]:
        ax, ay, z, zx, zPitch, opt = spec
        side = -1.0 if ax < self.HX - 20.0 else (1.0 if ax > self.HX + 20.0 else 0.0)
        depth = self.tune["depth"]
        if isinstance(z, (int, float)):
            px, py = self.rot_map(ax, ay, float(z) * depth, pose)
            if opt.get("lead"):
                lead_v = (
                    lerp(opt["lead"], opt["leadFit"], clamp(self.tune["mouthFit"], 0.0, 1.0))
                    if "leadFit" in opt
                    else opt["lead"]
                )
                px += float(z) * depth * lead_v * self.tune["solid"] * pose.sinY
            if opt.get("xz") and self.tune["eyeFit"] > 0.0:
                px += opt["xz"] * self.tune["eyeFit"] * depth * pose.sinY
        else:
            px, py = self.surf_map(z, ax, ay, pose)

        if zPitch:
            py = self.pitch_y(
                ay, zPitch * depth * pose.cosY * (1.0 if pose.sinP > 0.0 else self.PITCH["downK"]), pose
            )
        if opt.get("fit") and self.tune["faceFit"] > 0.0:
            fz = opt["fit"][0] if pose.sinP > 0.0 else opt["fit"][1]
            py2 = self.pitch_y(
                ay, fz * depth * pose.cosY * (1.0 if pose.sinP > 0.0 else self.PITCH["downK"]), pose
            )
            py = lerp(py, py2, min(self.tune["faceFit"], 1.0))

        sx = max(0.35, pose.cosY - zx * side * pose.sinY)
        sy = pose.cosP
        mb = 0.0
        if opt.get("mouthPitch"):
            ms = max(0.5, 1.0 - self.tune["mouthDownSize"] * max(0.0, -pose.sinP))
            sx *= ms
            sy *= ms
            mb = self.tune["mouthPitchBend"] * pose.sinP * opt["mouthPitch"]

        sh = 0.14 * pose.sinY * pose.sinP
        A = clamp(opt["asym"] * self.tune["solid"] * pose.sinY, -0.7 * sx, 0.7 * sx) if opt.get("asym") else 0.0
        g_px = opt.get("pxR", opt.get("px", ax)) if (pose.sinY > 0.0 and "pxR" in opt) else opt.get("px", ax)
        aw = opt.get("aw", 1.0)
        qk = clamp(self.tune["mouthFit"], 0.0, 1.0) if opt.get("round") else 0.0
        Q = (self.tune["solid"] * pose.sinY / (2.0 * opt["round"])) if qk > 0.0 else 0.0
        ql = 0.3 * sx / max(abs(Q), 1e-9) if qk > 0.0 else 0.0

        lx = x - ax
        ly = y - ay
        bx = 0.0
        if A:
            la = x - g_px
            bx = A * la * la / math.sqrt(la * la + aw * aw)
        if qk > 0.0:
            la = abs(x - g_px)
            l2 = min(la, ql)
            bx = lerp(bx, Q * l2 * (2.0 * la - l2), qk)
        ox = px + sx * lx - bx + pose.tiltT * ly
        oy = py + sh * lx + sy * ly
        if mb:
            u = lx / opt["mouthPitch"]
            oy += mb * u * u
        return ox, oy

    def frame_apply(
        self,
        frame_spec: dict,
        ax0: float,
        ay0: float,
        x: float,
        y: float,
        pose: Pose,
        stand_def: bool = False,
    ) -> tuple[float, float]:
        """Exact port of makeFrame() in avatar.js (before headPose)."""
        anchor = frame_spec.get("anchor")
        ax = float(anchor[0]) if anchor else ax0
        ay = float(anchor[1]) if anchor else ay0
        stand = frame_spec["stand"] if isinstance(frame_spec.get("stand"), bool) else stand_def

        surf_kind = frame_spec.get("surf")
        if surf_kind == "skin":
            fn = lambda px, py: self.surf_map(self.SKIN, px, py, pose)
        elif surf_kind == "ear":
            fn = lambda px, py: self.ear_deform(px, py, pose)
        elif surf_kind == "side":
            z_val = float(frame_spec.get("z", 0.3)) * self.R0
            zx_val = float(frame_spec.get("zx", 1.0))
            g_spec = (ax, ay, z_val, zx_val, 0.0, {})
            fn = lambda px, py: self.group_apply(g_spec, px, py, pose)
        elif self.model.get("hairClumps"):
            fn = lambda px, py: self.surf_map(self.SHELL["clumpFront"], px, py, pose)
        else:
            fn = lambda px, py: self.surf_map(self.SHELL["bangs"], px, py, pose)

        o0 = fn(ax, ay)
        lx = x - ax
        ly = y - ay
        if stand:
            return o0[0] + lx, o0[1] + ly

        h = 12.0
        o1 = fn(ax + h, ay)
        o2 = fn(ax, ay + h)
        j0 = (o1[0] - o0[0]) / h
        j1 = (o2[0] - o0[0]) / h
        j2 = (o1[1] - o0[1]) / h
        j3 = (o2[1] - o0[1]) / h
        return o0[0] + j0 * lx + j1 * ly, o0[1] + j2 * lx + j3 * ly

    def body_t(
        self,
        x: float,
        y: float,
        body_x: float = 0.0,
        body_z: float = 0.0,
        breath: float = 0.0,
    ) -> tuple[float, float]:
        """Exact port of bodyT() mapped from Live2D ParamBodyAngleX [-10,10], ParamBodyAngleZ [-10,10], ParamBreath [0,1]."""
        k = clamp((self.BODY_BOTTOM - y) / 1200.0, 0.0, 1.3)
        dx = x - 1500.0
        dy = y - self.BODY_BOTTOM
        # Scale Live2D standard [-10, 10] to natural Keshin2D motion amplitude
        sway = (body_x / 10.0) * 65.0
        roll = (body_z / 10.0) * 6.0 * DEG + (body_x / 10.0) * 0.02
        cr = math.cos(roll)
        sr = math.sin(roll)
        sx = sway * 0.35 * min(k, 1.0)
        b_amp = breath * 1.25
        sh = breath * 3.2
        ox = 1500.0 + dx * cr - dy * sr + sx + dx * 0.003 * b_amp * k
        oy = (
            self.BODY_BOTTOM
            + dx * sr
            + dy * cr
            - b_amp * 7.5 * k
            - sh * min(abs(dx) / 600.0, 1.0) * min(k, 1.0) * 0.5
        )
        return ox, oy

    @staticmethod
    def phys_shift(
        spec: dict,
        base_layer: dict,
        x: float,
        y: float,
        phi: float,
        phi2: Optional[float] = None,
        by: float = 0.0,
    ) -> tuple[float, float]:
        """Exact port of physShift() for rigid, pendulum, sprout, cloth, jelly."""
        ptype = spec["type"]
        defaults = {
            "jelly": {"tip": 1.6, "squash": 1.0},
            "cloth": {"tip": 1.7, "squash": 1.0},
            "pendulum": {"tip": 1.3, "squash": 0.0},
            "rigid": {"tip": 1.0, "squash": 0.0},
            "sprout": {"tip": 1.25, "squash": 2.5},
        }[ptype]
        tip = float(spec.get("tip", defaults["tip"]))
        squash = float(spec.get("squash", defaults["squash"]))
        pv = spec.get("pivot", [0.5, 0.0])
        bx, by0, bw, bh = float(base_layer["x"]), float(base_layer["y"]), float(base_layer["w"]), float(base_layer["h"])
        px = bx + pv[0] * bw
        py = by0 + pv[1] * bh
        plen = max(8.0, (float(spec["len"]) if isinstance(spec.get("len"), (int, float)) else (1.0 - pv[1])) * bh)
        up = max(8.0, py - by0)
        hw = max(8.0, bw / 2.0)
        rad = max(up, 0.9 * max(px - bx, bx + bw - px))
        if phi2 is None:
            phi2 = phi if spec.get("stiff") else phi * tip

        if ptype == "rigid":
            c, sn = math.cos(phi), math.sin(phi)
            dx, dy = x - px, y - py
            return px + dx * c - dy * sn, py + dx * sn + dy * c

        if ptype == "pendulum":
            d = y - py
            l = x - px
            if d <= 0.0:
                return x, y
            dd = min(d, plen)
            kap = (phi2 - phi) / plen
            a = phi + kap * dd
            if abs(kap * dd) < 1e-4:
                X = dd * math.sin(phi)
                Y = dd * math.cos(phi)
            else:
                X = (math.cos(phi) - math.cos(a)) / kap
                Y = (math.sin(a) - math.sin(phi)) / kap
            ex = d - dd
            ca, sa = math.cos(a), math.sin(a)
            return px + X + ex * sa + l * ca, py + Y + ex * ca - l * sa

        if ptype == "sprout":
            dx, dy = x - px, y - py
            qv = 0.07 * math.tanh(by * squash / 0.07) if by != 0.0 else 0.0
            a = phi + (phi2 - phi) * min(math.hypot(dx, dy) / rad, 1.0)
            ca, sa = math.cos(a), math.sin(a)
            X = dx * (1.0 - 0.5 * qv)
            Y = dy * (1.0 + qv)
            return px + X * ca - Y * sa, py + X * sa + Y * ca

        if ptype == "cloth":
            t = clamp((y - py) / plen, 0.0, 1.0)
            ox = x + plen * (phi * 0.7 * (t ** 1.6) + phi2 * 0.5 * (t ** 3))
            oy = y + plen * by * squash * (t ** 1.3)
            return ox, oy

        # jelly
        sq = by * squash
        base_scale = 1.0 - 0.20 * sq
        if y <= py:
            t = min((py - y) / up, 1.2)
            ox = px + (x - px) * (base_scale - 0.25 * sq * t) + up * (
                phi * 0.35 * (t ** 1.6) + (phi2 - phi * tip) * 0.10 * math.sin(math.pi * min(t, 1.0))
            )
            oy = py - (py - y) * (1.0 + sq * 0.85)
            return ox, oy
        r = min((y - py) / plen, 1.0)
        r2 = r * r
        ox = px + (x - px) * base_scale + plen * (phi2 * 0.65 * r2)
        oy = y + plen * (by * squash * 1.1) * r2
        return ox, oy

    @staticmethod
    def clump_bend(
        root: tuple[float, float],
        tip: tuple[float, float],
        grp: str,
        x: float,
        y: float,
        phi: float,
        u_side: float = 0.0,
    ) -> tuple[float, float]:
        """Exact port of clumpPart cantilever arc bending (length-preserving hair sway)."""
        rx, ry = float(root[0]), float(root[1])
        dx0, dy0 = float(tip[0]) - rx, float(tip[1]) - ry
        length = max(40.0, math.hypot(dx0, dy0))
        ux, uy = dx0 / length, dy0 / length
        wx, wy = uy, -ux
        t0 = 0.08 if grp == "back" else 0.20
        amax = 0.26 if grp == "bangs" else (0.42 if grp == "side" else 0.46)
        in_max = 0.09
        sg_in = (-1.0 if u_side < 0 else 1.0) if grp == "side" else 0.0
        cl_n = 24
        span = length * 1.35
        step = span / cl_n
        phi2 = phi * 1.35

        # Integrate cantilever spine
        tab_x = [0.0] * (cl_n + 1)
        tab_y = [0.0] * (cl_n + 1)
        tab_a = [0.0] * (cl_n + 1)
        X = Y = a0 = 0.0
        for i in range(1, cl_n + 1):
            tt = clamp((i * step / length - t0) / (1.0 - t0), 0.0, 1.3)
            a = phi * (tt ** 1.55) + phi2 * 0.72 * (tt ** 2.3)
            a = amax * math.tanh(a / amax)
            if sg_in and a * sg_in < 0.0:
                a = -sg_in * in_max * math.tanh(-a * sg_in / in_max)
            am = 0.5 * (a + a0)
            X += math.cos(am) * step
            Y += math.sin(am) * step
            a0 = a
            tab_x[i] = X
            tab_y[i] = Y
            tab_a[i] = a

        a_proj = (x - rx) * ux + (y - ry) * uy
        n_proj = (x - rx) * wx + (y - ry) * wy
        if a_proj <= 0.0:
            return x, y
        fi = min(a_proj / step, cl_n - 1e-3)
        idx = int(math.floor(fi))
        fr = fi - idx
        th = lerp(tab_a[idx], tab_a[idx + 1], fr)
        c, sn = math.cos(th), math.sin(th)
        ex = a_proj - min(a_proj, span)
        Xp = lerp(tab_x[idx], tab_x[idx + 1], fr) + ex * c - n_proj * sn
        Yp = lerp(tab_y[idx], tab_y[idx + 1], fr) + ex * sn + n_proj * c
        return rx + ux * Xp + wx * Yp, ry + uy * Xp + wy * Yp
