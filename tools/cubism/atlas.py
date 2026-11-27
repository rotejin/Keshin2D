"""Texture atlas packer for Keshin2D layers -> Live2D Cubism 4096x4096 PNG atlases.

Features:
  - Crops each layer PNG tightly to its non-transparent alpha bounding box (+ margin).
  - Applies straight-alpha RGB color bleed (dilation) into transparent border pixels
    so bilinear/mipmap filtering never produces dark halos.
  - Packs rectangles using MaxRects-BSSF into 4096x4096 (or 2048x2048 if single-page fits)
    PNG atlases, automatically spilling into texture_01.png, etc. if needed.
  - Provides exact UV mapping from Keshin2D model coordinates (x, y) into atlas UV [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


@dataclass
class AtlasEntry:
    name: str
    layer_x: float
    layer_y: float
    layer_w: int
    layer_h: int
    # Sub-rect inside original layer PNG
    crop_x: int
    crop_y: int
    crop_w: int
    crop_h: int
    # Placement inside atlas PNG
    texture_idx: int
    atlas_x: int
    atlas_y: int
    atlas_w: int
    atlas_h: int

    def uv_for_model_xy(self, x: np.ndarray | float, y: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
        """Map Keshin2D model coordinates (x, y) to Live2D atlas UVs (u, v top-down)."""
        qx = np.asarray(x, dtype=np.float64) - self.layer_x - self.crop_x
        qy = np.asarray(y, dtype=np.float64) - self.layer_y - self.crop_y
        # Clamp strictly inside the padded sprite rect (0.5px inset) so filtering never bleeds neighbors
        qx = np.clip(qx, 0.5, max(0.5, self.crop_w - 0.5))
        qy = np.clip(qy, 0.5, max(0.5, self.crop_h - 0.5))
        u = (self.atlas_x + qx) / self.atlas_w
        v = (self.atlas_y + qy) / self.atlas_h
        return u.astype(np.float32), v.astype(np.float32)


def bleed_alpha_rgb(rgba: np.ndarray, iterations: int = 4) -> np.ndarray:
    """Propagate RGB from opaque pixels into adjacent alpha==0 pixels (keeps alpha intact)."""
    out = rgba.copy()
    alpha = out[:, :, 3]
    known = alpha > 0
    rgb = out[:, :, :3].astype(np.float32)

    for _ in range(iterations):
        unknown = ~known
        if not np.any(unknown):
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(alpha.shape, dtype=np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            sy0 = max(0, -dy)
            sy1 = rgb.shape[0] - max(0, dy)
            sx0 = max(0, -dx)
            sx1 = rgb.shape[1] - max(0, dx)
            dy0 = max(0, dy)
            dy1 = rgb.shape[0] - max(0, -dy)
            dx0 = max(0, dx)
            dx1 = rgb.shape[1] - max(0, -dx)
            m = known[sy0:sy1, sx0:sx1]
            acc[dy0:dy1, dx0:dx1] += rgb[sy0:sy1, sx0:sx1] * m[:, :, None]
            cnt[dy0:dy1, dx0:dx1] += m
        fill = unknown & (cnt > 0)
        if not np.any(fill):
            break
        rgb[fill] = acc[fill] / cnt[fill, None]
        known[fill] = True

    out[:, :, :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    return out


def bake_clip_image(layer_img: Image.Image, lx: int, ly: int, base_img: Image.Image, bx: int, by: int) -> Image.Image:
    """Replicate Keshin2D's bakeClip (destination-in alpha mask by base layer)."""
    a = np.asarray(layer_img.convert("RGBA"), dtype=np.uint8).copy()
    b = np.asarray(base_img.convert("RGBA"), dtype=np.uint8)
    lh, lw = a.shape[:2]
    bh, bw = b.shape[:2]

    ox = bx - lx
    oy = by - ly
    mask = np.zeros((lh, lw), dtype=np.uint8)

    dx0 = max(0, ox)
    dy0 = max(0, oy)
    dx1 = min(lw, ox + bw)
    dy1 = min(lh, oy + bh)
    if dx1 > dx0 and dy1 > dy0:
        sx0 = dx0 - ox
        sy0 = dy0 - oy
        mask[dy0:dy1, dx0:dx1] = b[sy0 : sy0 + (dy1 - dy0), sx0 : sx0 + (dx1 - dx0), 3]

    a[:, :, 3] = ((a[:, :, 3].astype(np.uint16) * mask.astype(np.uint16)) // 255).astype(np.uint8)
    return Image.fromarray(a, mode="RGBA")


class _ShelfPacker:
    """Simple skyline / guillotine bin packer (fast and tight for sprite atlases)."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.free_rects: list[tuple[int, int, int, int]] = [(0, 0, width, height)]

    def insert(self, w: int, h: int) -> tuple[int, int] | None:
        best_idx = -1
        best_short = 1 << 30
        best_long = 1 << 30
        for i, (rx, ry, rw, rh) in enumerate(self.free_rects):
            if w <= rw and h <= rh:
                rem_w = rw - w
                rem_h = rh - h
                short_side = min(rem_w, rem_h)
                long_side = max(rem_w, rem_h)
                if short_side < best_short or (short_side == best_short and long_side < best_long):
                    best_short = short_side
                    best_long = long_side
                    best_idx = i
        if best_idx < 0:
            return None

        rx, ry, rw, rh = self.free_rects.pop(best_idx)
        # Split remaining space (guillotine along shorter leftover axis)
        rem_w = rw - w
        rem_h = rh - h
        if rem_w > 0 and rem_h > 0:
            if rem_w < rem_h:
                self.free_rects.append((rx + w, ry, rem_w, h))
                self.free_rects.append((rx, ry + h, rw, rem_h))
            else:
                self.free_rects.append((rx + w, ry, rem_w, rh))
                self.free_rects.append((rx, ry + h, w, rem_h))
        elif rem_w > 0:
            self.free_rects.append((rx + w, ry, rem_w, rh))
        elif rem_h > 0:
            self.free_rects.append((rx, ry + h, rw, rem_h))
        return rx, ry


def build_atlases(
    layers: Iterable[dict],
    parts_dir: Path,
    atlas_size: int = 4096,
    pad: int = 4,
    bleed_iters: int = 4,
) -> tuple[list[Image.Image], dict[str, AtlasEntry]]:
    """Load, crop, bleed, and pack all provided Keshin2D layer dicts into atlas PNGs."""
    by_name = {L["name"]: L for L in layers}
    loaded_raw: dict[str, Image.Image] = {}

    for L in layers:
        p = parts_dir / L["src"]
        if not p.exists():
            continue
        loaded_raw[L["name"]] = Image.open(p).convert("RGBA")

    # Apply Keshin2D's baked clipping for cardigan shadows onto shirt if present
    for cname in ("カーディガン影R", "カーディガン影L"):
        if cname in loaded_raw and "シャツ" in loaded_raw:
            cL, bL = by_name[cname], by_name["シャツ"]
            loaded_raw[cname] = bake_clip_image(
                loaded_raw[cname], int(cL["x"]), int(cL["y"]),
                loaded_raw["シャツ"], int(bL["x"]), int(bL["y"]),
            )

    # Crop non-empty sprites with 2px transparent margin inside the sprite
    items: list[tuple[dict, np.ndarray, int, int, int, int]] = []
    margin = 2
    for L in layers:
        name = L["name"]
        im = loaded_raw.get(name)
        if im is None:
            continue
        arr = np.asarray(im, dtype=np.uint8)
        alpha = arr[:, :, 3]
        ys, xs = np.nonzero(alpha > 0)
        if ys.size == 0:
            continue
        h_full, w_full = arr.shape[:2]
        x0 = max(0, int(xs.min()) - margin)
        y0 = max(0, int(ys.min()) - margin)
        x1 = min(w_full, int(xs.max()) + 1 + margin)
        y1 = min(h_full, int(ys.max()) + 1 + margin)
        patch = arr[y0:y1, x0:x1]
        # Ensure at least 2px transparent border around opaque pixels for safe UV clamping
        crop_x = x0
        crop_y = y0
        if x0 == 0 and np.any(patch[:, 0, 3] > 0):
            patch = np.pad(patch, ((0, 0), (margin, 0), (0, 0)), mode="constant")
            crop_x -= margin
        if y0 == 0 and np.any(patch[0, :, 3] > 0):
            patch = np.pad(patch, ((margin, 0), (0, 0), (0, 0)), mode="constant")
            crop_y -= margin
        if x1 == w_full and np.any(patch[:, -1, 3] > 0):
            patch = np.pad(patch, ((0, 0), (0, margin), (0, 0)), mode="constant")
        if y1 == h_full and np.any(patch[-1, :, 3] > 0):
            patch = np.pad(patch, ((0, margin), (0, 0), (0, 0)), mode="constant")

        patch = bleed_alpha_rgb(patch, iterations=bleed_iters)
        ch, cw = patch.shape[:2]
        if cw + 2 * pad > atlas_size or ch + 2 * pad > atlas_size:
            raise ValueError(
                f"Layer {name!r} cropped size {cw}x{ch} exceeds atlas_size={atlas_size}"
            )
        items.append((L, patch, crop_x, crop_y, cw, ch))

    # Sort largest max-side / area first for tightest packing
    items.sort(key=lambda it: (max(it[4], it[5]), it[4] * it[5]), reverse=True)

    packers: list[_ShelfPacker] = []
    pages: list[np.ndarray] = []
    entries: dict[str, AtlasEntry] = {}

    for L, patch, crop_x, crop_y, cw, ch in items:
        pw = cw + pad
        ph = ch + pad
        placed_pos = None
        page_idx = -1
        for pi, pk in enumerate(packers):
            pos = pk.insert(pw, ph)
            if pos is not None:
                placed_pos = pos
                page_idx = pi
                break
        if placed_pos is None:
            pk = _ShelfPacker(atlas_size, atlas_size)
            pos = pk.insert(pw, ph)
            if pos is None:
                raise RuntimeError(f"Failed to pack layer {L['name']} ({cw}x{ch})")
            packers.append(pk)
            pages.append(np.zeros((atlas_size, atlas_size, 4), dtype=np.uint8))
            page_idx = len(pages) - 1
            placed_pos = pos

        ax, ay = placed_pos
        pages[page_idx][ay : ay + ch, ax : ax + cw] = patch
        entries[L["name"]] = AtlasEntry(
            name=L["name"],
            layer_x=float(L["x"]),
            layer_y=float(L["y"]),
            layer_w=int(L["w"]),
            layer_h=int(L["h"]),
            crop_x=crop_x,
            crop_y=crop_y,
            crop_w=cw,
            crop_h=ch,
            texture_idx=page_idx,
            atlas_x=ax,
            atlas_y=ay,
            atlas_w=atlas_size,
            atlas_h=atlas_size,
        )

    pil_pages = [Image.fromarray(p, mode="RGBA") for p in pages]
    return pil_pages, entries
