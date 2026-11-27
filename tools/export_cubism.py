# -*- coding: utf-8 -*-
"""Export a Keshin2D model to Live2D Cubism (.moc3 / .model3.json) format.

Usage:
  python tools/export_cubism.py kurage02
  python tools/export_cubism.py models/Yakuko exported_cubism/Yakuko
  python tools/export_cubism.py chiwa out/chiwa --moc-version 3 --atlas-size 4096

Requires numpy and pillow (see tools/requirements.txt).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.cubism.converter import convert_keshin_to_cubism


def resolve_input_dir(target: str) -> Path:
    p = Path(target)
    if (p / "model.json").is_file():
        return p
    cand = ROOT / "models" / target
    if (cand / "model.json").is_file():
        return cand
    raise FileNotFoundError(
        f"Could not find model.json in {p} or {cand}"
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="Export a Keshin2D model to Live2D Cubism (.moc3 + .model3.json + atlases + physics + expressions)."
    )
    ap.add_argument(
        "model",
        help="Model name under models/ (e.g. kurage02, chiwa) or path to a model directory containing model.json",
    )
    ap.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Output directory (default: exported_cubism/<name>)",
    )
    ap.add_argument("--name", type=str, default=None, help="Output model name (default: input folder name)")
    ap.add_argument("--moc-version", type=int, default=3, choices=[3, 4], help=".moc3 format version (default: 3)")
    ap.add_argument("--atlas-size", type=int, default=4096, help="Texture atlas size in pixels (default: 4096)")
    args = ap.parse_args()

    in_dir = resolve_input_dir(args.model)
    model_name = args.name or in_dir.name
    out_dir = Path(args.output_dir) if args.output_dir else (ROOT / "exported_cubism" / model_name)

    summary = convert_keshin_to_cubism(
        model_dir=in_dir,
        out_dir=out_dir,
        model_name=model_name,
        moc_version=args.moc_version,
        atlas_size=args.atlas_size,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
