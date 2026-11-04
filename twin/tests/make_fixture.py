#!/usr/bin/env python3
"""DEV/TEST ONLY - writes SYNTHETIC .raw files in LTspice's binary format so the bridge + dashboard can be
tested before real LTspice runs exist. It is NOT circuit data: node values are crude stand-ins built from the
README's measured numbers. The .raw Title says SYNTHETIC and the dashboard shows a red banner.
Never use this output in a demo or report. Real data: python aqsense_twin.py run"""
import sys; from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aqsense_twin as A

def fixture(name, sc):
    dt = 50e-6; t = np.arange(0, sc["end"], dt); p = np.array(sc["pts"], float)
    V, F = np.interp(t, p[:, 0], p[:, 1]), np.interp(t, p[:, 0], p[:, 2])
    ph = 2 * np.pi * np.cumsum(F) * dt; ma = A.VPK_PER_VRMS * V * np.sin(ph)
    m, b = np.polyfit(*A.CAL_V, 1); rip = 0.04 * np.sin(2 * np.pi * 100 * t)
    vs = m * V + b + rip                                        # README's measured VSENSE-vs-mains fit
    refs = [3.605, 4.062, 4.973, 5.430]; hi, lo = 8.98, .135
    L = [vs > r for r in refs]; ov = L[3]; uv = ~L[0]
    gate = uv | ov; buz = np.where(gate & (np.sin(2 * np.pi * 980 * t) > 0), 8.5, 0.0)
    sh = np.zeros_like(t); cur = 0.0
    for i in range(len(t)): cur = vs[i] if ov[i] else cur; sh[i] = cur
    tgt = 2.3282 + .0465 * (F - 50); fv = np.zeros_like(t); a = dt / 0.12; x = 0.0
    for i in range(len(t)): x += a * (tgt[i] - x); fv[i] = x
    fh, fl = fv > 2.3743, fv < 2.2823
    cols = dict(vreg_out=np.full_like(t, 9.0), vsense=vs, sh_out=sh, freq_v=fv,
                comp1_out=np.where(L[0], lo, hi), comp2_out=np.where(L[1], lo, hi), comp3_out=np.where(L[2], lo, hi),
                comp4_out=np.where(L[3], lo, hi), comp4_inv=np.where(ov, hi, lo), or_out=np.where(gate, 1.12, .40),
                buzzer_out=buz, freq_hi=np.where(fh, lo, hi), freq_lo=np.where(fl, lo, hi),
                freq_ok_n=np.where(fh | fl, hi, lo), mains_a=ma, mains_b=np.zeros_like(t))
    names = A.SAVE; nv = len(names) + 1
    head = ("Title: * SYNTHETIC TEST FIXTURE - NOT LTSPICE\nDate: n/a\nPlotname: Transient Analysis\nFlags: real forward\n"
            f"No. Variables: {nv}\nNo. Points: {len(t)}\nOffset:\t0.0000000000000000e+000\nCommand: synthetic\nVariables:\n\t0\ttime\ttime\n"
            + "".join(f"\t{i+1}\tV({n})\tvoltage\n" for i, n in enumerate(names)) + "Binary:\n")
    rec = np.zeros(len(t), np.dtype([("t", "<f8"), ("v", "<f4", (nv - 1,))])); rec["t"] = t
    rec["v"] = np.stack([cols[n] for n in names], 1)
    A.WORK.mkdir(exist_ok=True)
    (A.WORK / f"{name}.raw").write_bytes(head.encode("utf-16-le") + rec.tobytes())
    print("fixture:", name)

if __name__ == "__main__":
    for n, s in A.SCN.items(): fixture(n, s)
