"""Generate Live2D Cubism .exp3.json expression files matching Keshin2D's EXPR presets."""

from __future__ import annotations

import math

DEG = math.pi / 180.0

# Exact EXPR dictionary from Keshin2D/js/avatar.js (when keyEye / keyMouth active)
KESHIN_EXPRS: dict[str, dict] = {
    "smile_soft": {
        "jp": "にこ",
        "eyeSmile": 1.0,
        "cheek": 0.35,
        "browY": 0.15,
        "mouth": "closed",
    },
    "smile_big": {
        "jp": "笑顔",
        "eyeSmile": 1.0,
        "eyeMul": 0.0,
        "cheek": 0.5,
        "browY": 0.3,
        "browForm": 0.3,
        "mouth": "laugh",
    },
    "happy": {
        "jp": "わーい",
        "eyeMul": 1.15,
        "browY": 0.55,
        "cheek": 0.45,
        "mouth": "tri",
    },
    "grin": {
        "jp": "にしし",
        "eyeSmile": 1.0,
        "eyeMul": 0.0,
        "cheek": 0.5,
        "browY": 0.2,
        "mouth": "grin",
    },
    "smug": {
        "jp": "にやり",
        "eyeMul": 0.62,
        "eyeTilt": 0.35,
        "browAngle": 0.35,
        "browY": -0.15,
        "cheek": 0.3,
        "mouth": "smug",
    },
    "wink": {
        "jp": "ウインク",
        "eyeMulR": 0.0,
        "eyeSmile": 1.0,
        "cheek": 0.4,
        "browY": 0.2,
        "mouth": "grin",
    },
    "closed_eyes": {
        "jp": "閉じ目",
        "eyeMul": 0.0,
    },
    "surprised": {
        "jp": "びっくり",
        "eyeMul": 1.2,
        "irisSize": -0.6,
        "browY": 0.8,
        "mouth": "round",
    },
    "blank": {
        "jp": "ぽかん",
        "eyeMul": 1.1,
        "browY": 0.35,
        "mouth": "u",
    },
    "stare": {
        "jp": "ジト目",
        "eyeJito": 1.0,
        "browY": -0.3,
        "browAngle": 0.2,
        "mouth": "pout",
    },
    "angry": {
        "jp": "怒り",
        "eyeTilt": 1.0,
        "browAngle": 1.0,
        "browY": -0.45,
        "browShow": 0.85,
        "mouth": "he",
    },
    "troubled": {
        "jp": "困り",
        "eyeTilt": -1.0,
        "browAngle": -0.9,
        "browY": 0.1,
        "cheek": 0.2,
        "mouth": "wavy",
    },
    "cat_mouth": {
        "jp": "ω",
        "cheek": 0.2,
        "mouth": "omega",
    },
    "blush": {
        "jp": "照れ",
        "diffs": ["赤面"],
        "eyeSmile": 0.7,
        "browAngle": -0.3,
        "mouth": "omega",
    },
    "scorn": {
        "jp": "蔑む",
        "diffs": ["蔑む", "闇"],
        "eyeJito": 0.8,
        "browAngle": 0.35,
        "browY": -0.3,
        "browShow": 0.85,
        "mouth": "he",
    },
    "pale": {
        "jp": "青ざめ",
        "diffs": ["青ざめ", "涙"],
        "eyeTilt": -0.8,
        "browAngle": -0.8,
        "mouth": "wavy",
    },
    "heart_eyes": {
        "jp": "ハート",
        "diffs": ["赤面", "ハート"],
        "mouth": "small",
    },
    "sparkle_eyes": {
        "jp": "キラキラ",
        "diffs": ["しいたけ"],
        "eyeMul": 1.1,
        "browY": 0.4,
        "mouth": "a",
    },
    "dizzy": {
        "jp": "ぐるぐる",
        "diffs": ["ぐるぐる", "汗"],
        "browAngle": -0.8,
        "mouth": "square",
    },
    "dark": {
        "jp": "闇",
        "diffs": ["黒", "闇"],
        "eyeMul": 0.9,
        "mouth": "closed",
    },
    "tehe": {
        "jp": "てへ",
        "diffs": ["赤面"],
        "eyeMulR": 0.0,
        "eyeSmile": 1.0,
        "browAngle": -0.3,
        "mouth": "smug",
    },
}

DIFF_PARAM_MAP = {
    "赤面": "ParamCheek",
    "青ざめ": "ParamDiffPale",
    "黒": "ParamDiffDarkFace",
    "蔑む": "ParamDiffScorn",
    "涙": "ParamDiffTear",
    "汗": "ParamDiffSweat",
    "ハート": "ParamDiffHeart",
    "しいたけ": "ParamDiffSparkle",
    "ぐるぐる": "ParamDiffSwirl",
    "闇": "ParamDiffDarkEye",
}


def build_expressions(
    model: dict,
    available_params: set[str],
    phys_specs: list[tuple[str, dict]],
) -> dict[str, dict]:
    """Build dict[expr_filename_stem, exp3_json_dict] for all Keshin2D expressions."""
    out: dict[str, dict] = {}
    for slug, cfg in KESHIN_EXPRS.items():
        jp = cfg["jp"]
        params: list[dict] = []

        def add_p(pid: str, val: float, blend: str = "Add") -> None:
            if pid in available_params:
                params.append({"Id": pid, "Value": round(float(val), 4), "Blend": blend})

        if "eyeMul" in cfg:
            add_p("ParamEyeLOpen", cfg["eyeMul"], "Multiply")
            add_p("ParamEyeROpen", cfg["eyeMul"], "Multiply")
        if "eyeMulR" in cfg:
            add_p("ParamEyeROpen", cfg["eyeMulR"], "Multiply")
        if "eyeMulL" in cfg:
            add_p("ParamEyeLOpen", cfg["eyeMulL"], "Multiply")

        if cfg.get("eyeSmile"):
            add_p("ParamEyeLSmile", cfg["eyeSmile"], "Add")
            add_p("ParamEyeRSmile", cfg["eyeSmile"], "Add")

        eye_tilt = cfg.get("eyeTilt", 0.0)
        eye_jito = cfg.get("eyeJito", 0.0)
        if eye_tilt > 0.4 and "ParamEyeGlare" in available_params:
            add_p("ParamEyeExprHide", 1.0, "Overwrite")
            add_p("ParamEyeGlare", 1.0, "Overwrite")
        elif eye_tilt < -0.4 and "ParamEyeSad" in available_params:
            add_p("ParamEyeExprHide", 1.0, "Overwrite")
            add_p("ParamEyeSad", 1.0, "Overwrite")
        elif eye_jito > 0.4 and "ParamEyeJito" in available_params:
            add_p("ParamEyeExprHide", 1.0, "Overwrite")
            add_p("ParamEyeJito", 1.0, "Overwrite")

        if cfg.get("irisSize"):
            add_p("ParamIrisSize", cfg["irisSize"], "Add")

        if cfg.get("browY"):
            add_p("ParamBrowLY", cfg["browY"], "Add")
            add_p("ParamBrowRY", cfg["browY"], "Add")
        if cfg.get("browAngle"):
            add_p("ParamBrowLAngle", cfg["browAngle"], "Add")
            add_p("ParamBrowRAngle", cfg["browAngle"], "Add")
        if cfg.get("browForm"):
            add_p("ParamBrowLForm", cfg["browForm"], "Add")
            add_p("ParamBrowRForm", cfg["browForm"], "Add")
        if cfg.get("browShow"):
            add_p("ParamBrowShow", cfg["browShow"], "Add")

        cheek = float(cfg.get("cheek", 0.0))
        diffs = list(cfg.get("diffs") or [])
        if "赤面" in diffs:
            cheek = max(cheek, 1.0)
        if cheek > 0.0:
            add_p("ParamCheek", cheek, "Add")
        for d in diffs:
            if d == "赤面":
                continue
            dpid = DIFF_PARAM_MAP.get(d)
            if dpid:
                add_p(dpid, 1.0, "Overwrite")

        mouth_key = cfg.get("mouth")
        if mouth_key and mouth_key != "closed":
            mpid = f"ParamMouthExpr_{mouth_key}"
            if mpid in available_params:
                add_p("ParamMouthExprHide", 1.0, "Overwrite")
                add_p(mpid, 1.0, "Overwrite")

        # Expressive physics offsets (e.g. Yakuko's fox/cat ears perk up or droop per expression!)
        for pid, spec in phys_specs:
            expr_map = spec.get("expr")
            if isinstance(expr_map, dict) and jp in expr_map:
                deg_val = float(expr_map[jp])
                max_rad = float(spec.get("max", 0.25))
                if max_rad > 1e-4:
                    norm_val = max(-1.0, min(1.0, (deg_val * DEG) / max_rad))
                    add_p(pid, norm_val, "Add")

        if params:
            out[slug] = {
                "Type": "Live2D Expression",
                "FadeInTime": 0.25,
                "FadeOutTime": 0.25,
                "Parameters": params,
            }
    return out
