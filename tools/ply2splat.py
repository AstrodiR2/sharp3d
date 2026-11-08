#!/usr/bin/env python3
"""SHARP .ply (3DGS) -> antimatter15 .splat (32 B/splat) + meta.json"""
import argparse, json, sys
from pathlib import Path
import numpy as np
from plyfile import PlyData

C0 = 0.28209479177387814

ap = argparse.ArgumentParser()
ap.add_argument("src", type=Path, help="ply file or dir with ply")
ap.add_argument("dst", type=Path, help="output dir")
ap.add_argument("--max", type=int, default=600000)
a = ap.parse_args()

src = a.src
if src.is_dir():
    plys = sorted(src.glob("*.ply"))
    if not plys:
        sys.exit(f"no .ply in {src}")
    src = plys[0]
print("reading", src)

ply = PlyData.read(str(src))
v = ply["vertex"].data
f = lambda *names: np.stack([np.asarray(v[n], dtype=np.float32) for n in names], 1)

xyz = f("x", "y", "z")
sc = np.exp(f("scale_0", "scale_1", "scale_2"))
op = 1.0 / (1.0 + np.exp(-np.asarray(v["opacity"], dtype=np.float32)))
dc = f("f_dc_0", "f_dc_1", "f_dc_2")
q = f("rot_0", "rot_1", "rot_2", "rot_3")  # w,x,y,z

ok = np.isfinite(xyz).all(1) & np.isfinite(sc).all(1) & np.isfinite(q).all(1) & np.isfinite(op) & (op > 0.02)
idx = np.nonzero(ok)[0]

# angular-size importance: opacity * cbrt(volume) / depth
vol = np.cbrt(np.prod(sc, 1))
imp = op * vol / np.maximum(xyz[:, 2], 0.1)
imp[~ok] = -1
if len(idx) > a.max:
    idx = np.argsort(-imp)[: a.max]
print(f"{len(v)} -> {len(idx)} gaussians")

xyz, sc, op, dc, q = xyz[idx], sc[idx], op[idx], dc[idx], q[idx]
q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-12

out = np.zeros(len(idx), dtype=np.dtype([("pos", "<f4", 3), ("scale", "<f4", 3), ("rgba", "u1", 4), ("rot", "u1", 4)]))
out["pos"] = xyz
out["scale"] = sc
out["rgba"][:, :3] = np.clip((0.5 + C0 * dc) * 255, 0, 255).astype(np.uint8)
out["rgba"][:, 3] = np.clip(op * 255, 0, 255).astype(np.uint8)
out["rot"] = np.clip(q * 128 + 128, 0, 255).astype(np.uint8)
assert out.dtype.itemsize == 32

meta = {"count": int(len(idx)), "zc": float(np.median(xyz[:, 2]))}
try:
    iw, ih = [int(x) for x in ply["image_size"].data["image_size"]]
    fpx = float(ply["intrinsic"].data["intrinsic"][0])
    meta.update(width=iw, height=ih, f_px=fpx)
except Exception as e:
    print("no intrinsics in ply, fallback:", e)
    meta.update(width=1536, height=1536, f_px=1536.0)

a.dst.mkdir(parents=True, exist_ok=True)
(a.dst / "scene.splat").write_bytes(out.tobytes())
(a.dst / "meta.json").write_text(json.dumps(meta))
print(meta)
