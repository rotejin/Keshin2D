"""Generate Live2D Cubism .physics3.json from Keshin2D model.json physics & hair config."""

from __future__ import annotations

import math


def _make_pendulum_setting(
    setting_id: str,
    inputs: list[tuple[str, float, str, bool]],
    outputs: list[tuple[str, int, float, float, str, bool]],
    particles: list[tuple[float, float, float, float, float, float]],
    pos_range: tuple[float, float, float] = (-10.0, 0.0, 10.0),
    ang_range: tuple[float, float, float] = (-10.0, 0.0, 10.0),
) -> dict:
    return {
        "Id": setting_id,
        "Input": [
            {
                "Source": {"Target": "Parameter", "Id": src_id},
                "Weight": float(weight),
                "Type": typ,
                "Reflect": bool(reflect),
            }
            for src_id, weight, typ, reflect in inputs
        ],
        "Output": [
            {
                "Destination": {"Target": "Parameter", "Id": dst_id},
                "VertexIndex": int(vidx),
                "Scale": float(scale),
                "Weight": float(weight),
                "Type": typ,
                "Reflect": bool(reflect),
            }
            for dst_id, vidx, scale, weight, typ, reflect in outputs
        ],
        "Vertices": [
            {
                "Position": {"X": float(x), "Y": float(y)},
                "Mobility": float(mob),
                "Delay": float(delay),
                "Acceleration": float(acc),
                "Radius": float(rad),
            }
            for x, y, mob, delay, acc, rad in particles
        ],
        "Normalization": {
            "Position": {
                "Minimum": float(pos_range[0]),
                "Default": float(pos_range[1]),
                "Maximum": float(pos_range[2]),
            },
            "Angle": {
                "Minimum": float(ang_range[0]),
                "Default": float(ang_range[1]),
                "Maximum": float(ang_range[2]),
            },
        },
    }


def build_physics3(model: dict, phys_param_ids: list[tuple[str, dict]]) -> dict:
    """Build a valid Cubism 3 .physics3.json dict for hair and all model.physics accessories."""
    settings: list[dict] = []
    dictionary: list[dict] = []

    sway_scale = float((model.get("tune") or {}).get("sway", 1.5)) / 1.5
    sway_scale = max(0.3, min(2.0, sway_scale))

    # 1. Hair Front (bangs)
    settings.append(
        _make_pendulum_setting(
            "PhysicsHairFront",
            inputs=[
                ("ParamAngleX", 55.0, "X", False),
                ("ParamAngleZ", 45.0, "Angle", False),
                ("ParamBodyAngleX", 20.0, "X", False),
            ],
            outputs=[
                ("ParamHairFront", 1, round(1.8 * sway_scale, 3), 100.0, "Angle", False),
            ],
            particles=[
                (0.0, 0.0, 1.0, 1.0, 1.0, 0.0),
                (0.0, 10.0, 0.92, 0.85, 1.6, 10.0),
                (0.0, 20.0, 0.85, 0.80, 1.8, 10.0),
            ],
        )
    )
    dictionary.append({"Id": "PhysicsHairFront", "Name": "Hair Front"})

    # 2. Hair Side
    settings.append(
        _make_pendulum_setting(
            "PhysicsHairSide",
            inputs=[
                ("ParamAngleX", 60.0, "X", False),
                ("ParamAngleZ", 60.0, "Angle", False),
                ("ParamBodyAngleX", 25.0, "X", False),
            ],
            outputs=[
                ("ParamHairSide", 1, round(2.2 * sway_scale, 3), 65.0, "Angle", False),
                ("ParamHairSide", 2, round(2.4 * sway_scale, 3), 35.0, "Angle", False),
            ],
            particles=[
                (0.0, 0.0, 1.0, 1.0, 1.0, 0.0),
                (0.0, 12.0, 0.95, 0.88, 1.4, 12.0),
                (0.0, 24.0, 0.90, 0.82, 1.6, 12.0),
            ],
        )
    )
    dictionary.append({"Id": "PhysicsHairSide", "Name": "Hair Side"})

    # 3. Hair Back
    settings.append(
        _make_pendulum_setting(
            "PhysicsHairBack",
            inputs=[
                ("ParamAngleX", 55.0, "X", True),
                ("ParamAngleZ", 65.0, "Angle", False),
                ("ParamBodyAngleX", 30.0, "X", False),
            ],
            outputs=[
                ("ParamHairBack", 1, round(2.4 * sway_scale, 3), 60.0, "Angle", False),
                ("ParamHairBack", 2, round(2.6 * sway_scale, 3), 40.0, "Angle", False),
            ],
            particles=[
                (0.0, 0.0, 1.0, 1.0, 1.0, 0.0),
                (0.0, 14.0, 0.95, 0.90, 1.3, 14.0),
                (0.0, 28.0, 0.90, 0.85, 1.5, 14.0),
            ],
        )
    )
    dictionary.append({"Id": "PhysicsHairBack", "Name": "Hair Back"})

    # 4. Custom model.physics accessories (kemomimi ears, tail, earrings, ahoge, ribbons, hats...)
    for param_id, spec in phys_param_ids:
        sid = f"Physics_{spec['id']}"
        ptype = spec.get("type", "pendulum")
        attach = spec.get("attach", "hat")
        k = float(spec.get("k", 90.0))
        c = float(spec.get("c", 6.5))
        gain = float(spec.get("gain", 1.0))

        # Map spring stiffness k and damping c into Cubism pendulum parameters
        freq = math.sqrt(max(k, 10.0)) / (2.0 * math.pi)
        delay = max(0.55, min(0.96, 1.0 - 0.08 * min(freq, 3.0)))
        acc = max(0.8, min(2.4, 0.9 + 0.35 * min(freq, 3.0)))
        zeta = c / (2.0 * math.sqrt(max(k, 10.0)))
        mob = max(0.70, min(0.98, 1.02 - 0.25 * zeta))
        out_scale = round(max(0.8, min(4.0, 2.0 * gain * sway_scale)), 3)

        if attach == "body":
            inputs = [
                ("ParamBodyAngleX", 70.0, "X", False),
                ("ParamBodyAngleZ", 50.0, "Angle", False),
                ("ParamAngleX", 25.0, "X", False),
            ]
        else:
            inputs = [
                ("ParamAngleX", 60.0, "X", False),
                ("ParamAngleY", 25.0, "Y", False),
                ("ParamAngleZ", 60.0, "Angle", False),
            ]

        reflect = ptype in ("sprout", "pendulum")
        settings.append(
            _make_pendulum_setting(
                sid,
                inputs=inputs,
                outputs=[
                    (param_id, 1, out_scale, 100.0, "Angle", reflect),
                ],
                particles=[
                    (0.0, 0.0, 1.0, 1.0, 1.0, 0.0),
                    (0.0, 10.0, round(mob, 3), round(delay, 3), round(acc, 3), 10.0),
                ],
            )
        )
        dictionary.append({"Id": sid, "Name": spec.get("label", spec["id"])})

    total_in = sum(len(s["Input"]) for s in settings)
    total_out = sum(len(s["Output"]) for s in settings)
    total_v = sum(len(s["Vertices"]) for s in settings)

    return {
        "Version": 3,
        "Meta": {
            "PhysicsSettingCount": len(settings),
            "TotalInputCount": total_in,
            "TotalOutputCount": total_out,
            "VertexCount": total_v,
            "Fps": 60,
            "EffectiveForces": {
                "Gravity": {"X": 0.0, "Y": -1.0},
                "Wind": {"X": 0.0, "Y": 0.0},
            },
            "PhysicsDictionary": dictionary,
        },
        "PhysicsSettings": settings,
    }
