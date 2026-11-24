"""Gaussian-splat PLY (3DGS export: Scaniverse, Polycam, Luma...) -> clean coloured mesh GLB for `make scan-import`.

A splat is not a mesh: this keeps the splat centres (with their base colour), crops them in the item's own frame,
strips clutter, fills the hidden surface under removed clutter, and voxel-meshes the rest (Geometry Nodes
Points to Volume -> Volume to Mesh) with vertex colours sampled from the nearest splat.

Run in Blender:
  blender -b --python scripts/splat_mesh.py -- --src <splat.ply> --out <mesh.glb> [options]
Frame: metres, z up, floor at z=0, origin at the item centre, long axis on +X (front side chosen with --flip).
  --band z0,z1        height band (m above floor) whose points define the item's centre + long axis (e.g. a tabletop)
  --keep u0,u1,v0,v1,z0,z1   (repeatable) keep only points inside the union of these boxes (item frame, m)
  --strip u0,u1,v0,v1,z0     (repeatable) delete points above z0 in this footprint (clutter on a surface)
  --fill u0,u1,v0,v1,z[,su0,su1,sv0,sv1,sz]  (repeatable) add surface points at height z where the footprint has
                      none (under clutter), coloured from the optional source footprint at height sz
  --flatten u0,u1,v0,v1,z0,z (repeatable) move everything above z0 in the footprint to height z (uneven leaves -> one top)
  --drop-cool Z       drop bluish/grey splats above Z (sky-coloured fringe around edges)
  --smooth N / --flat-top Z / --color-blur N   mesh clean-up: smooth surfaces, one exact top plane, even colours
  --views DIR         write top/front/side PNGs of the kept points (to choose boxes), then continue
  --views-only        stop after the views (no mesh)
"""
import argparse
import math
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

SH0 = 0.28209479177387814


def load_ply(path):
    with open(path, "rb") as f:
        hdr = b""
        while not hdr.endswith(b"end_header\n"):
            line = f.readline()
            if not line:
                sys.exit("ERROR: no PLY header")
            hdr += line
        lines = hdr.split(b"\n")
        if not any(b"binary_little_endian" in l for l in lines):
            sys.exit("ERROR: only binary_little_endian splat PLYs are supported")
        props = [l.split()[-1].decode() for l in lines if l.startswith(b"property")]
        if any(not l.startswith(b"property float") for l in lines if l.startswith(b"property")):
            sys.exit("ERROR: expected float properties only (3DGS layout)")
        n = int([l for l in lines if l.startswith(b"element vertex")][0].split()[-1])
        a = np.frombuffer(f.read(n * 4 * len(props)), dtype="<f4").reshape(n, len(props))
    d = {p: a[:, i] for i, p in enumerate(props)}
    for need in ("x", "y", "z", "f_dc_0", "opacity", "scale_0"):
        if need not in d:
            sys.exit(f"ERROR: not a Gaussian-splat PLY (no '{need}'); a plain point cloud can only be used to measure")
    return d


def write_png(path, img):
    img = np.clip(img, 0, 255).astype(np.uint8)
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[r].tobytes() for r in range(h))

    def ch(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))


def view(U, V, C, ur, vr, ppu, depth, grid=0.25):
    """Orthographic colour image (nearest point wins) with a grid every `grid` m; the 0 lines are bright."""
    w, h = int((ur[1] - ur[0]) * ppu), int((vr[1] - vr[0]) * ppu)
    iu = ((U - ur[0]) * ppu).astype(int)
    iv = ((vr[1] - V) * ppu).astype(int)
    m = (iu >= 0) & (iu < w) & (iv >= 0) & (iv < h)
    iu, iv, C, dp = iu[m], iv[m], C[m], depth[m]
    o = np.argsort(-dp)
    img = np.full((h, w, 3), 30.0)
    img[iv[o], iu[o]] = C[o]
    for g in np.arange(math.ceil(ur[0] / grid) * grid, ur[1], grid):
        x = int((g - ur[0]) * ppu)
        img[:, x] = img[:, x] * 0.5 + (255 if abs(g) < 1e-6 else 110) * 0.5
    for g in np.arange(math.ceil(vr[0] / grid) * grid, vr[1], grid):
        y = int((vr[1] - g) * ppu)
        if 0 <= y < h:
            img[y] = img[y] * 0.5 + (255 if abs(g) < 1e-6 else 110) * 0.5
    return img


def boxes(specs, n):
    out = []
    for s in specs:
        v = [float(t) for t in s.split(",")]
        if len(v) != n:
            sys.exit(f"ERROR: expected {n} numbers in '{s}'")
        out.append(v)
    return out


def in_box(P, u0, u1, v0, v1, z0, z1):
    return (P[:, 0] >= u0) & (P[:, 0] <= u1) & (P[:, 1] >= v0) & (P[:, 1] <= v1) & (P[:, 2] >= z0) & (P[:, 2] <= z1)


def close_gaps(P, C, zmax, r, step):
    """Morphological closing (dilate then erode by r) of the occupied voxels below zmax; every newly solid voxel
    gets a point coloured like its nearest scanned point. Fills holes and missing chunks smaller than ~2r."""
    sel = P[:, 2] < zmax
    Q = P[sel]
    lo = Q.min(0) - r - 2 * step
    idx = np.floor((Q - lo) / step).astype(int)
    k = max(1, int(round(r / step)))
    shape = idx.max(0) + k + 3
    occ = np.zeros(shape, bool)
    occ[tuple(idx.T)] = True

    def grow(g, val):  # 6-neighbour dilation (val=True) / erosion (val=False), k steps -> octahedral ball
        for _ in range(k):
            h = g.copy()
            for ax in range(3):
                for s in (1, -1):
                    sh = np.roll(g, s, axis=ax)
                    h = (h | sh) if val else (h & sh)
            g = h
        return g
    closed = grow(grow(occ, True), False)
    new = np.argwhere(closed & ~occ)
    if not len(new):
        return P, C
    F = lo + (new + 0.5) * step
    from mathutils.kdtree import KDTree
    kd = KDTree(len(Q))
    for i, p in enumerate(Q):
        kd.insert(p, i)
    kd.balance()
    QC = C[sel]
    col = np.array([QC[kd.find(p)[1]] for p in F])
    print(f"SPLAT: closed {len(F)} empty voxels below z {zmax} (radius {r} m)")
    return np.vstack([P, F]), np.vstack([C, col])


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(prog="splat_mesh.py")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out")
    ap.add_argument("--up", choices=["-y", "y", "z"], default="-y", help="source up axis (3DGS/COLMAP: -y)")
    ap.add_argument("--opacity", type=float, default=0.5, help="drop splats less opaque than this")
    ap.add_argument("--max-splat", type=float, default=0.03, help="drop splats whose largest axis is over this (m): fog/floaters")
    ap.add_argument("--floor", type=float, default=None, help="override auto floor height in source z (m) when tabletop outnumbers floor")
    ap.add_argument("--band", default="0.68,0.80")
    ap.add_argument("--yaw", type=float, help="override the auto long-axis angle (deg)")
    ap.add_argument("--flip", action="store_true", help="turn the item 180 deg (front side to the other long edge)")
    ap.add_argument("--keep", action="append", default=[])
    ap.add_argument("--strip", action="append", default=[])
    ap.add_argument("--flatten", action="append", default=[],
                    help="u0,u1,v0,v1,z0,z: points above z0 in this footprint are moved to height z (one flat top, colours kept)")
    ap.add_argument("--move", action="append", default=[],
                    help="u0,u1,v0,v1,z0,z1,du,dv,dz: shift the points in a box (line up a part that scanned off-axis)")
    ap.add_argument("--mirror", action="append", default=[],
                    help="u|v,c,u0,u1,v0,v1,z0,z1: add a mirror copy of the points in a box across u=c or v=c "
                         "(a symmetric part scanned better on one side fills the other)")
    ap.add_argument("--close", metavar="Z,R",
                    help="below height Z (m), close holes up to ~2R across (voxel closing) and fill them with points")
    ap.add_argument("--box", action="append", default=[],
                    help="u0,u1,v0,v1,z0,z1[,pad]: normalize a straight rectangular member (leg/rail) by clearing "
                         "noisy splats within pad (default 0.03 m) and filling the exact box with a uniform lattice "
                         "coloured from the scanned splats of that member")
    ap.add_argument("--fill", action="append", default=[])
    ap.add_argument("--fill-step", type=float, default=0.008)
    ap.add_argument("--drop-cool", type=float, default=None, metavar="Z",
                    help="drop bluish/grey splats (blue >= red) above this height: sky-coloured fringe, not wood")
    ap.add_argument("--min-neighbours", type=int, default=6, help="drop splats in 2 cm cells with fewer than this many")
    ap.add_argument("--voxel", type=float, default=0.008, help="voxel size (m) for meshing")
    ap.add_argument("--radius", type=float, default=0.012, help="point radius (m) for meshing")
    ap.add_argument("--smooth", type=int, default=0, help="Laplacian smoothing iterations on the mesh (0 = off)")
    ap.add_argument("--smooth-below", metavar="Z,N",
                    help="N more (stronger, plain Laplacian) smoothing passes on the mesh below height Z (m): lumpy legs")
    ap.add_argument("--flat-top", type=float, metavar="Z",
                    help="snap up-facing mesh vertices above Z (m) to one height (their median): a dead-flat top")
    ap.add_argument("--color-blur", type=int, default=0, help="neighbour-average the vertex colours this many times")
    ap.add_argument("--views")
    ap.add_argument("--views-only", action="store_true")
    a = ap.parse_args(argv)

    d = load_ply(a.src)
    X, Y, Z = (d[c].astype(np.float64) for c in "xyz")
    # to z-up, right-handed (proper rotations only, never a mirror)
    if a.up == "-y":
        P = np.stack([X, Z, -Y], 1)
    elif a.up == "y":
        P = np.stack([X, -Z, Y], 1)
    else:
        P = np.stack([X, Y, Z], 1)
    op = 1 / (1 + np.exp(-d["opacity"]))
    sc = np.exp(np.stack([d["scale_0"], d["scale_1"], d["scale_2"]], 1)).max(1)
    C = np.clip(0.5 + SH0 * np.stack([d["f_dc_0"], d["f_dc_1"], d["f_dc_2"]], 1), 0, 1)
    k = (op >= a.opacity) & (sc <= a.max_splat)
    P, C = P[k], C[k]
    print(f"SPLAT: {len(k)} splats, {k.sum()} kept (opacity >= {a.opacity}, size <= {a.max_splat} m)")

    # floor = the most populated thin height layer in the central region (unless overridden by --floor)
    core = np.all(np.abs(P[:, :2] - np.median(P[:, :2], 0)) < 3, 1)
    if a.floor is not None:
        floor = float(a.floor)
    else:
        hz, e = np.histogram(P[core, 2], bins=400, range=np.percentile(P[core, 2], [1, 99]))
        floor = float((e[hz.argmax()] + e[hz.argmax() + 1]) / 2)
    P[:, 2] -= floor
    print(f"SPLAT: floor at {floor:.3f} m (source)")

    b0, b1 = (float(t) for t in a.band.split(","))
    band = (P[:, 2] > b0) & (P[:, 2] < b1) & core
    Q = P[band, :2]
    c = np.median(Q, 0)
    for _ in range(2):  # trim far stragglers before PCA
        r = np.linalg.norm(Q - c, axis=1)
        Q = Q[r < np.percentile(r, 97)]
        c = Q.mean(0)
    w, V = np.linalg.eigh(np.cov((Q - c).T))
    yaw = a.yaw if a.yaw is not None else math.degrees(math.atan2(V[1, 1], V[0, 1]))
    if a.flip:
        yaw += 180
    t = math.radians(-yaw)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    P[:, :2] = (P[:, :2] - c) @ R.T
    print(f"SPLAT: frame centre {c.round(3).tolist()} m, long axis {yaw:.2f} deg -> +X")

    if a.keep:
        m = np.zeros(len(P), bool)
        for u0, u1, v0, v1, z0, z1 in boxes(a.keep, 6):
            m |= (P[:, 0] >= u0) & (P[:, 0] <= u1) & (P[:, 1] >= v0) & (P[:, 1] <= v1) & (P[:, 2] >= z0) & (P[:, 2] <= z1)
        P, C = P[m], C[m]
        print(f"SPLAT: {len(P)} splats inside the keep boxes")
    strips = boxes(a.strip, 5)
    if a.drop_cool is not None:
        m = (P[:, 2] > a.drop_cool) & (C[:, 2] >= C[:, 0])
        P, C = P[~m], C[~m]
        print(f"SPLAT: dropped {m.sum()} cool-coloured splats above z {a.drop_cool}")
    for u0, u1, v0, v1, z0 in strips:
        m = (P[:, 0] >= u0) & (P[:, 0] <= u1) & (P[:, 1] >= v0) & (P[:, 1] <= v1) & (P[:, 2] > z0)
        P, C = P[~m], C[~m]
        print(f"SPLAT: stripped {m.sum()} splats above z {z0} in {u0},{u1},{v0},{v1}")

    for u0, u1, v0, v1, z0, z in boxes(a.flatten, 6):
        m = (P[:, 0] >= u0) & (P[:, 0] <= u1) & (P[:, 1] >= v0) & (P[:, 1] <= v1) & (P[:, 2] > z0)
        P[m, 2] = z + np.random.default_rng(1).normal(0, 0.002, m.sum())
        print(f"SPLAT: flattened {m.sum()} splats above z {z0} to z {z} in {u0},{u1},{v0},{v1}")

    for u0, u1, v0, v1, z0, z1, du, dv, dz in boxes(a.move, 9):
        m = in_box(P, u0, u1, v0, v1, z0, z1)
        P[m] += (du, dv, dz)
        print(f"SPLAT: moved {m.sum()} splats by {du},{dv},{dz} in {u0},{u1},{v0},{v1},{z0},{z1}")
    for spec in a.mirror:
        ax, c, *bx = spec.split(",")
        if ax not in ("u", "v") or len(bx) != 6:
            sys.exit(f"ERROR: --mirror wants u|v,c,u0,u1,v0,v1,z0,z1 (got '{spec}')")
        m = in_box(P, *(float(t) for t in bx))
        i = "uv".index(ax)
        Q = P[m].copy()
        Q[:, i] = 2 * float(c) - Q[:, i]
        P, C = np.vstack([P, Q]), np.vstack([C, C[m]])
        print(f"SPLAT: mirrored {m.sum()} splats across {ax} = {c}")

    # drop isolated floaters: sparse 2 cm cells
    cell = np.floor(P / 0.02).astype(np.int64)
    key = (cell[:, 0] * 73856093) ^ (cell[:, 1] * 19349663) ^ (cell[:, 2] * 83492791)
    _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    m = cnt[inv] >= a.min_neighbours
    print(f"SPLAT: dropped {(~m).sum()} isolated splats (< {a.min_neighbours} per 2 cm cell)")
    P, C = P[m], C[m]

    if a.box:
        from mathutils.kdtree import KDTree
        P_src, C_src = P.copy(), C.copy()
        s = a.fill_step
        box_pts, box_cols = [], []
        for spec in a.box:
            f = [float(t) for t in spec.split(",")]
            if len(f) not in (6, 7):
                sys.exit(f"ERROR: --box wants u0,u1,v0,v1,z0,z1[,pad] (got '{spec}')")
            u0, u1, v0, v1, z0, z1 = f[:6]
            pad = f[6] if len(f) == 7 else 0.03
            if pad >= 0:
                z_lo = z0 - pad if z0 > 0.1 else z0
                clr = in_box(P, u0 - pad, u1 + pad, v0 - pad, v1 + pad, z_lo, z1)
                P, C = P[~clr], C[~clr]
            gu = np.linspace(u0, u1, max(2, int(round((u1 - u0) / s)) + 1))
            gv = np.linspace(v0, v1, max(2, int(round((v1 - v0) / s)) + 1))
            gz = np.linspace(z0, z1, max(2, int(round((z1 - z0) / s)) + 1))
            U, V, Z = np.meshgrid(gu, gv, gz, indexing="ij")
            G = np.column_stack([U.ravel(), V.ravel(), Z.ravel()])
            # keep only surface shell (within 1.5*s of a face) so vertex count stays lean while volume is solid
            shell = (G[:, 0] <= u0 + 1.5 * s) | (G[:, 0] >= u1 - 1.5 * s) | \
                    (G[:, 1] <= v0 + 1.5 * s) | (G[:, 1] >= v1 - 1.5 * s) | \
                    (G[:, 2] <= z0 + 1.5 * s) | (G[:, 2] >= z1 - 1.5 * s)
            G = G[shell]
            sm = in_box(P_src, u0 - 0.04, u1 + 0.04, v0 - 0.04, v1 + 0.04, z0 - 0.02, z1 + 0.02)
            # prefer upper/well-lit wood splats (luma > 0.35) for the member's median tone so shadow pockets don't blotch
            SP, SC = P_src[sm], C_src[sm]
            if not len(SC):
                SP, SC = P_src, C_src
            lit = SC.mean(1) > 0.35
            med = np.median(SC[lit] if lit.any() else SC, 0)
            kd = KDTree(len(SP))
            for idx_p, pt in enumerate(SP):
                kd.insert(pt, idx_p)
            kd.balance()
            near_c = np.array([SC[kd.find(pt)[1]] for pt in G])
            col = np.clip(near_c * 0.4 + med * 0.6, 0, 1)
            box_pts.append(G)
            box_cols.append(col)
            med_hex = "#%02x%02x%02x" % tuple(int(round(x * 255)) for x in med)
            print(f"SPLAT: normalized box {u0},{u1},{v0},{v1},{z0},{z1} ({len(G)} pts, colour ~{med_hex})")
        P = np.vstack([P] + box_pts)
        C = np.vstack([C] + box_cols)

    for spec in a.fill:
        f = [float(t) for t in spec.split(",")]
        if len(f) not in (5, 10):
            sys.exit(f"ERROR: --fill wants u0,u1,v0,v1,z[,su0,su1,sv0,sv1,sz] (got '{spec}')")
        u0, u1, v0, v1, z = f[:5]
        s = a.fill_step
        gu, gv = np.meshgrid(np.arange(u0, u1 + 1e-9, s), np.arange(v0, v1 + 1e-9, s))
        G = np.stack([gu.ravel(), gv.ravel()], 1)
        near = (np.abs(P[:, 2] - z) < 0.02) & (P[:, 0] >= u0 - 0.02) & (P[:, 0] <= u1 + 0.02) & \
               (P[:, 1] >= v0 - 0.02) & (P[:, 1] <= v1 + 0.02)
        S = P[near]
        # colour source: the given footprint + height (same finish elsewhere), else the clean surface at this
        # height outside the strip boxes - never what was left under clutter
        if len(f) == 10:
            su0, su1, sv0, sv1, sz = f[5:]
            src = (np.abs(P[:, 2] - sz) < 0.03) & (P[:, 0] >= su0) & (P[:, 0] <= su1) & (P[:, 1] >= sv0) & (P[:, 1] <= sv1)
        else:
            src = np.abs(P[:, 2] - z) < 0.03
            for s0, s1, t0, t1, _ in strips:
                src &= ~((P[:, 0] >= s0) & (P[:, 0] <= s1) & (P[:, 1] >= t0) & (P[:, 1] <= t1))
        SC = C[src]
        occ = set(map(tuple, np.floor(S[:, :2] / (2 * s)).astype(int)))
        empty = np.array([tuple(g) not in occ for g in np.floor(G / (2 * s)).astype(int)])
        G = G[empty]
        if len(G) and len(SC):
            # colour: the median surface colour of this footprint, with the real grain jitter of its splats
            rng = np.random.default_rng(0)
            col = SC[rng.integers(0, len(SC), len(G))] * 0.4 + np.median(SC, 0) * 0.6
            F = np.column_stack([G, np.full(len(G), z) + rng.normal(0, 0.002, len(G))])
            P, C = np.vstack([P, F]), np.vstack([C, col])
        med = "#%02x%02x%02x" % tuple(int(round(x * 255)) for x in np.median(SC, 0)) if len(SC) else "-"
        print(f"SPLAT: filled {len(G)} surface points at z {z} in {u0},{u1},{v0},{v1} (colour ~{med})")

    if a.close:
        P, C = close_gaps(P, C, *(float(t) for t in a.close.split(",")), step=a.voxel)

    print(f"SPLAT: extent u {P[:, 0].min():.3f}..{P[:, 0].max():.3f}  v {P[:, 1].min():.3f}..{P[:, 1].max():.3f}  "
          f"z {P[:, 2].min():.3f}..{P[:, 2].max():.3f} m")
    if a.views:
        out = Path(a.views)
        out.mkdir(parents=True, exist_ok=True)
        rgb = C * 255
        ur = (P[:, 0].min() - 0.2, P[:, 0].max() + 0.2)
        vr = (P[:, 1].min() - 0.2, P[:, 1].max() + 0.2)
        zr = (-0.05, P[:, 2].max() + 0.1)
        write_png(out / "top.png", view(P[:, 0], P[:, 1], rgb, ur, vr, 250, -P[:, 2]))
        write_png(out / "front.png", view(P[:, 0], P[:, 2], rgb, ur, zr, 250, P[:, 1]))  # from -Y
        write_png(out / "side.png", view(P[:, 1], P[:, 2], rgb, vr, zr, 250, -P[:, 0]))   # from +X
        print(f"VIEWS: {out}/top.png front.png side.png (grid 0.25 m)")
    if a.views_only:
        return
    if not a.out:
        sys.exit("ERROR: --out needed to mesh")
    mesh_points(P, C, a)


def finish_mesh(ob, a):
    """Smooth the voxel surface, flatten the top, even out colours, smooth shading."""
    import bpy
    me = ob.data
    n = len(me.vertices)
    E = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", E)
    E = E.reshape(-1, 2)
    deg = np.bincount(E.ravel(), minlength=n).astype(np.float64)[:, None]
    deg[deg == 0] = 1

    def neighbour_mean(X):
        acc = np.zeros_like(X)
        np.add.at(acc, E[:, 0], X[E[:, 1]])
        np.add.at(acc, E[:, 1], X[E[:, 0]])
        return acc / deg

    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    for _ in range(a.smooth):  # Taubin (lambda/mu) smoothing: removes voxel bumps without shrinking thin parts much
        co += 0.5 * (neighbour_mean(co) - co)
        co -= 0.53 * (neighbour_mean(co) - co)
    if a.smooth:
        print(f"MESH: smoothed ({a.smooth} Taubin iterations)")
    if a.smooth_below:
        zb, nb = a.smooth_below.split(",")
        low = co[:, 2] < float(zb)
        for _ in range(int(nb)):  # plain Laplacian: irons out lumps a few cm across (thin parts shrink a little)
            co[low] += 0.5 * (neighbour_mean(co) - co)[low]
        print(f"MESH: extra smoothing below z {zb} ({nb} passes, {low.sum()} verts)")
    if a.flat_top is not None:
        me.vertices.foreach_set("co", co.ravel())
        me.update()
        nz = np.empty(n * 3)
        me.vertices.foreach_get("normal", nz)
        up = (co[:, 2] > a.flat_top) & (nz.reshape(-1, 3)[:, 2] > 0.2)
        if up.any():
            z = float(np.median(co[up, 2]))
            co[up, 2] = z
            print(f"MESH: flattened {up.sum()} top vertices to z {z:.4f} m")
    me.vertices.foreach_set("co", co.ravel())
    ca = me.color_attributes["Col"]
    col = np.empty(n * 4, dtype=np.float32)
    ca.data.foreach_get("color", col)
    col = col.reshape(-1, 4).astype(np.float64)
    for _ in range(a.color_blur):
        col = 0.5 * col + 0.5 * neighbour_mean(col)
    if a.color_blur:
        print(f"MESH: colours blurred ({a.color_blur} passes)")
    if a.flat_top is not None and up.any():
        # one even colour on the flat top: decimation stretches vertex colours across long triangles into streaks
        col[up] = np.median(col[up], axis=0)
        print("MESH: flat top given one colour (median of its vertices)")
    ca.data.foreach_set("color", col.astype(np.float32).ravel())
    me.update()
    me.shade_smooth()
    # flat faces (the top) stay flat-shaded: decimation turns a plane into long thin triangles whose smoothed
    # normals lean toward the rim and streak
    fn = np.empty(len(me.polygons) * 3)
    me.polygons.foreach_get("normal", fn)
    flat = np.abs(fn.reshape(-1, 3)[:, 2]) > 0.97
    me.polygons.foreach_set("use_smooth", (~flat).tolist())
    me.update()
    print(f"MESH: smooth shading ({flat.sum()} near-horizontal faces kept flat)")
    if a.flat_top is not None and up.any():
        # merge the dead-flat top into a few big polygons: tens of thousands of tiny coplanar faces otherwise get
        # collapse-decimated on import into slivers that shade as dark streaks
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        topf = {f for f in bm.faces if all(up[v.index] for v in f.verts)}
        edges = list({e for f in topf for e in f.edges if len(e.link_faces) == 2 and all(g in topf for g in e.link_faces)})
        n0 = len(bm.faces)
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(1), verts=[], edges=edges, delimit=set())
        print(f"MESH: flat top merged ({n0} -> {len(bm.faces)} faces)")
        bm.to_mesh(me)
        bm.free()
        me.update()


def set_mode(node, menu_item, enum_id):
    """Resolution Mode is a menu socket in Blender 4.4+ and a node enum before."""
    if "Resolution Mode" in node.inputs:
        node.inputs["Resolution Mode"].default_value = menu_item
    else:
        node.resolution_mode = enum_id


def mesh_points(P, C, a):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    me = bpy.data.meshes.new("pts")
    me.vertices.add(len(P))
    me.vertices.foreach_set("co", P.astype(np.float32).ravel())
    col = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    rgba = np.column_stack([C ** 2.2, np.ones(len(C))]).astype(np.float32)  # sRGB-ish -> linear
    col.data.foreach_set("color", rgba.ravel())
    pts = bpy.data.objects.new("pts", me)
    bpy.context.scene.collection.objects.link(pts)

    # Geometry Nodes: points -> volume -> mesh, colour from the nearest splat
    ng = bpy.data.node_groups.new("splat_mesh", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gin, gout = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    m2p = N.new("GeometryNodeMeshToPoints")
    m2p.inputs["Radius"].default_value = a.radius
    p2v = N.new("GeometryNodePointsToVolume")
    set_mode(p2v, "Size", "VOXEL_SIZE")
    p2v.inputs["Voxel Size"].default_value = a.voxel
    p2v.inputs["Density"].default_value = 1.0
    p2v.inputs["Radius"].default_value = a.radius
    v2m = N.new("GeometryNodeVolumeToMesh")
    set_mode(v2m, "Grid", "GRID")
    v2m.inputs["Threshold"].default_value = 0.1
    near = N.new("GeometryNodeSampleNearest")
    near.domain = "POINT"
    samp = N.new("GeometryNodeSampleIndex")
    samp.data_type = "FLOAT_COLOR"
    samp.domain = "POINT"
    attr = N.new("GeometryNodeInputNamedAttribute")
    attr.data_type = "FLOAT_COLOR"
    attr.inputs["Name"].default_value = "Col"
    store = N.new("GeometryNodeStoreNamedAttribute")
    store.data_type = "FLOAT_COLOR"
    store.domain = "POINT"
    store.inputs["Name"].default_value = "Col"
    L.new(gin.outputs[0], m2p.inputs["Mesh"])
    L.new(m2p.outputs[0], p2v.inputs[0])
    L.new(p2v.outputs[0], v2m.inputs[0])
    L.new(gin.outputs[0], near.inputs[0])
    L.new(gin.outputs[0], samp.inputs[0])
    L.new(attr.outputs[0], samp.inputs["Value"])
    L.new(near.outputs[0], samp.inputs["Index"])
    L.new(v2m.outputs[0], store.inputs[0])
    L.new(samp.outputs[0], store.inputs["Value"])
    L.new(store.outputs[0], gout.inputs[0])
    mod = pts.modifiers.new("splat_mesh", "NODES")
    mod.node_group = ng
    bpy.context.view_layer.objects.active = pts
    pts.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    print(f"MESH: {len(pts.data.vertices)} verts, {len(pts.data.polygons)} faces (voxel {a.voxel} m)")
    pts.data.color_attributes.active_color = pts.data.color_attributes["Col"]

    mat = bpy.data.materials.new("scan_vertex_colour")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    ca = nt.nodes.new("ShaderNodeVertexColor")
    ca.layer_name = "Col"
    nt.links.new(ca.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.85
    pts.data.materials.append(mat)
    finish_mesh(pts, a)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=True, export_cameras=False, export_lights=False)
    print(f"EXPORTED {out}")


if __name__ == "__main__":
    main()
