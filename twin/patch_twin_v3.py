#!/usr/bin/env python3
"""Run inside aqsense/twin:  python3 patch_twin_v3.py
Adds: R19 sweep scenarios (hidden from the dashboard), s6 buffered memory control, s7/s8 characterisation ramps,
and two commands:  python3 aqsense_twin.py sweep   |   python3 aqsense_twin.py characterise"""
from pathlib import Path
A = "aqsense_twin.py"
def sub(old, new):
    s = Path(A).read_text(encoding="utf-8"); assert old in s, "pattern not found:\n" + old[:90]
    Path(A).write_text(s.replace(old, new, 1), encoding="utf-8")

# 1. scenarios ------------------------------------------------------------------------------------------------
SCN_CODE = '''# ---- v3 scenarios: R19 sweep, buffered memory control, characterisation ramps -----------------------------
_SG = [(0, 236, 50), (1.6, 236, 50), (2.1, 284, 50), (3.5, 284, 50), (4.1, 236, 50), (5.5, 236, 50)]
_SM = [(0, .9, "Power-up"), (.9, 1.6, "Healthy"), (1.6, 3.5, "Surge to 284 V"), (3.5, 5.5, "Recovery")]
SWEEP = [(470, "sw_r19_470"), (680, "s5_memfix"), (820, "sw_r19_820"), (1000, "sw_r19_1k"), (2200, "sw_r19_2k2"), (10000, "sw_r19_10k")]
for _r, _n in SWEEP:
    if _n not in SCN:
        SCN[_n] = dict(title=f"R19 sweep, {_r} ohm", end=5.5, hide=True, rep={"R19": str(_r)}, mod=f"R19 = {_r} ohm",
                       desc="R19 sweep point.", pts=_SG, marks=_SM)
SCN["s6_bufctl"] = dict(title="What-if: buffered memory control", end=5.5, swap={"U7": (1, "SH_CTRL")}, xsave=["sh_ctrl"],
    add=["XU6B V_MID COMP4_OUT VREG_OUT 0 SH_CTRL LM339  ; WHAT-IF: spare comparator dedicated to the memory switch",
         "R19B VREG_OUT SH_CTRL 10000"],
    mod="Spare comparator drives the memory switch. COMP4_INV and R19 unchanged. Design what-if, not the original circuit.",
    desc="Same surge as scenario 5 with the original R19.", pts=_SG, marks=_SM)
SCN["s7_vramp"] = dict(title="Characterisation: voltage ramp", end=15.1, ramp=(2.6, 8.85, 15.1),
    desc="Slow ramp 178 V to 290 V and back (18.7 V/s) to measure the comparator trip points.",
    pts=[(0, 236, 50), (1.6, 236, 50), (2.1, 178, 50), (2.6, 178, 50), (8.6, 290, 50), (9.1, 290, 50), (15.1, 178, 50)],
    marks=[(0, .9, "Power-up"), (.9, 1.6, "Healthy"), (1.6, 2.6, "Step down to 178 V"), (2.6, 8.85, "Slow ramp up, 18.7 V/s"),
           (8.85, 15.1, "Slow ramp down, 18.7 V/s")])
SCN["s8_framp"] = dict(title="Characterisation: frequency ramp", end=12.6, ramp=(2.6, 7.6, 12.6),
    desc="Slow ramp 46 Hz to 54 Hz and back (1.6 Hz/s) to measure the window trip points.",
    pts=[(0, 236, 50), (1.6, 236, 50), (2.1, 236, 46), (2.6, 236, 46), (7.6, 236, 54), (12.6, 236, 46)],
    marks=[(0, .9, "Power-up"), (.9, 1.6, "Healthy"), (1.6, 2.6, "Step to 46 Hz"), (2.6, 7.6, "Slow ramp up, 1.6 Hz/s"),
           (7.6, 12.6, "Slow ramp down, 1.6 Hz/s")])
_ORDER = ["s1_normal", "s2_voltage", "s3_frequency", "s4_generator", "s5_memfix", "s6_bufctl", "s7_vramp", "s8_framp"]
SCN = {k: SCN[k] for k in _ORDER + [k for k in SCN if k not in _ORDER]}

'''
MAKE_HDR = "# ---------------------------------------------------------------------------------------------- make"
sub(MAKE_HDR, SCN_CODE + MAKE_HDR)

# 2. netlist edits: node swap + added lines + per-scenario extra .save ------------------------------------------
sub('''            elif u.startswith("v1 "):''', '''            elif p and p[0].upper().startswith("X") and any(p[0].upper().endswith(k) for k in sc.get("swap", {})):
                k = next(k for k in sc["swap"] if p[0].upper().endswith(k)); p[sc["swap"][k][0]] = sc["swap"][k][1]
                line = " ".join(p) + "  ; WHAT-IF: node changed"
            elif u.startswith("v1 "):''')
sub('''        out += [".save " + " ".join(f"V({n})" for n in SAVE), ".options plotwinsize=0", ".end"]''',
    '''        out += sc.get("add", [])
        out += [".save " + " ".join(f"V({n})" for n in SAVE + sc.get("xsave", [])), ".options plotwinsize=0", ".end"]''')

# 3. dashboard only shows non-hidden scenarios -------------------------------------------------------------------
sub('''for n in SCN if (DATA / f"{n}.json").exists()]''', '''for n in SCN if (DATA / f"{n}.json").exists() and not SCN[n].get("hide")]''')

# 4. new commands ------------------------------------------------------------------------------------------------
CMD_CODE = '''def _find(n):
    return next((WORK / f"{n}{e}" for e in (".raw", ".csv", ".txt") if (WORK / f"{n}{e}").exists()), None)

def sweep():
    """R19 sweep: does the memory capture, does the buzzer still sound, what does the LM339 have to sink?"""
    rows = []
    for lab, r, n in [(f"{r} ohm", r, n) for r, n in SWEEP] + [("buffered", 10000, "s6_bufctl")]:
        f = _find(n)
        if not f: print(f"  {n}: no data yet, skipped"); continue
        tr = load(f); t = tr["time"]; W = lambda k, a, b: tr[f"v({k})"][(t >= a) & (t < b)]
        ck = "sh_ctrl" if "v(sh_ctrl)" in tr else "comp4_inv"
        vreg = W("vreg_out", 1, 1.5).mean(); low = W("comp4_inv", 1, 1.5).mean()
        ctl = W(ck, 2.6, 3.3).mean(); orov = W("or_out", 2.6, 3.3).mean(); orn = W("or_out", 1, 1.5).mean()
        duty = (W("buzzer_out", 2.6, 3.3) > vreg / 2).mean(); sh = W("sh_out", 4.8, 5.4).mean()
        rows.append(dict(case=lab, r19=r, ctl=ctl, or_ov=orov, or_norm=orn, low=low, sink_mA=(vreg - low) / r * 1e3,
                         sh_end=sh, captures=bool(sh >= 4.3), buzzer=bool(duty > .2)))
    if not rows: sys.exit("No sweep data yet. Run the sw_* scenarios in LTspice first.")
    print(f"{'case':>10} {'ctl V':>6} {'OR ov V':>8} {'OR norm V':>10} {'low V':>6} {'sink mA':>8} {'SH held V':>10}  memory   buzzer")
    for x in rows:
        print(f"{x['case']:>10} {x['ctl']:6.2f} {x['or_ov']:8.2f} {x['or_norm']:10.2f} {x['low']:6.2f} {x['sink_mA']:8.2f} {x['sh_end']:10.2f}  "
              f"{'captured' if x['captures'] else 'NOT'}  {'sounds' if x['buzzer'] else 'SILENT'}")
    OUT.mkdir(exist_ok=True); keys = list(rows[0])
    (OUT / "r19_sweep.csv").write_text(",".join(keys) + "\\n" + "\\n".join(",".join(str(x[k]) for k in keys) for x in rows) + "\\n")
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    except ImportError:
        print("Table saved to out/r19_sweep.csv. For the plot: sudo apt install -y python3-matplotlib"); return
    sw = [x for x in rows if x["case"] != "buffered"]; bf = next((x for x in rows if x["case"] == "buffered"), None)
    fig, ax = plt.subplots(1, 2, figsize=(10.5, 4), dpi=150)
    X = [x["r19"] for x in sw]
    ax[0].semilogx(X, [x["ctl"] for x in sw], "-", color="#1f3a5f", lw=1.2)
    ax[0].scatter(X, [x["ctl"] for x in sw], c=["#2f7d4f" if x["captures"] else "#b3261e" for x in sw], zorder=3, s=36)
    ax[0].axhline(2.16, color="#b7791f", ls="--", lw=1); ax[0].axhline(5.0, color="#2f7d4f", ls="--", lw=1)
    ax[0].text(X[0], 2.25, "switch starts to conduct (2.16 V)", fontsize=7, color="#b7791f"); ax[0].text(X[0], 5.1, "fully closed (about 5 V)", fontsize=7, color="#2f7d4f")
    if bf: ax[0].axhline(bf["ctl"], color="#6a7077", ls=":", lw=1.4); ax[0].text(X[0], bf["ctl"] + .1, "buffered control line, R19 = 10k", fontsize=7, color="#6a7077")
    ax[0].set(xlabel="R19 (ohm)", ylabel="Memory switch control level during surge (V)", title="Control level vs R19 (green = memory captured)")
    ax[1].semilogx(X, [x["sink_mA"] for x in sw], "o-", color="#1f3a5f", lw=1.2, ms=5)
    ax[1].axhline(6, color="#b3261e", ls="--", lw=1); ax[1].text(X[0], 6.2, "LM339 datasheet minimum sink, about 6 mA (verify)", fontsize=7, color="#b3261e")
    ax[1].set(xlabel="R19 (ohm)", ylabel="Current sunk by U6 in normal state (mA)", title="Cost of a lower R19")
    for a in ax: a.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(OUT / "r19_sweep.png"); print("Saved out/r19_sweep.csv and out/r19_sweep.png")

def characterise():
    """Trip points from the slow ramps: up-ramp crossing, down-ramp crossing, their mean (lag-free) and the offset from design."""
    jobs = [("s7_vramp", "vr", "V", [("l1", "LED1", 180), ("l2", "LED2", 200), ("l3", "LED3", 240), ("l4", "LED4", 260)]),
            ("s8_framp", "fa", "Hz", [("fl", "FREQ_LO flag", 49), ("fh", "FREQ_HI flag", 51)])]
    rows, loaded = [], []
    for name, ak, unit, sigs in jobs:
        f = DATA / f"{name}.json"
        if not f.exists(): print(f"  {name}: not extracted yet, skipped"); continue
        d = json.loads(f.read_text()); x = d[ak]; r0, rs, r1 = SCN[name]["ramp"]; loaded.append((name, ak, unit, sigs, d))
        for key, lab, des in sigs:
            cr = crossings(np.array(d[key], float), int(r0 / BIN))
            up = [x[i] for i, _ in cr if (i + .5) * BIN < rs]; dn = [x[i] for i, _ in cr if (i + .5) * BIN >= rs]
            u, w = (up[0] if up else None), (dn[0] if dn else None)
            m = (u + w) / 2 if u is not None and w is not None else None
            rows.append((lab, unit, des, u, w, m))
    if not rows: sys.exit("No ramp data yet. Run s7_vramp and s8_framp in LTspice, then extract.")
    fm = lambda v, d=1: "n/a" if v is None else f"{v:.{d}f}"
    print(f"{'signal':>14} {'design':>7} {'up-ramp':>8} {'down-ramp':>10} {'mean':>7} {'offset':>7} {'up-down':>8}")
    lines = ["signal,unit,design,up_ramp,down_ramp,mean,offset,up_minus_down"]
    for lab, unit, des, u, w, m in rows:
        off = None if m is None else m - des; hy = None if u is None or w is None else u - w
        print(f"{lab:>14} {des:>5} {unit:>2} {fm(u):>8} {fm(w):>10} {fm(m):>7} {fm(off):>7} {fm(hy):>8}")
        lines.append(",".join([lab, unit, str(des), fm(u, 3), fm(w, 3), fm(m, 3), fm(off, 3), fm(hy, 3)]))
    OUT.mkdir(exist_ok=True); (OUT / "characterisation.csv").write_text("\\n".join(lines) + "\\n")
    print("Saved out/characterisation.csv  (mean of up and down crossings cancels the FREQ_V filter lag)")
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    except ImportError:
        print("For the plot: sudo apt install -y python3-matplotlib"); return
    fig, axs = plt.subplots(1, len(loaded), figsize=(5.2 * len(loaded), 4), dpi=150, squeeze=False)
    cols = ["#1f3a5f", "#2f7d4f", "#b7791f", "#b3261e"]
    for a, (name, ak, unit, sigs, d) in zip(axs[0], loaded):
        r0, rs, r1 = SCN[name]["ramp"]; ix = np.arange(len(d["t"])); tm = (ix + .5) * BIN
        upm, dnm = (tm > r0) & (tm < rs), (tm >= rs) & (tm < r1); x = np.array(d[ak], float)
        for c, (key, lab, des) in zip(cols, sigs):
            y = np.array(d[key], float); a.plot(x[upm], y[upm], color=c, lw=1.4, label=f"{lab} up"); a.plot(x[dnm], y[dnm], color=c, lw=1.2, ls="--")
            a.axvline(des, color=c, lw=.8, ls=":")
        a.set(xlabel=f"Applied mains ({unit})", ylabel="Fraction of time output low (1 = indicator on)", title=SCN[name]["title"] + "  (solid up, dashed down, dotted design)")
        a.title.set_fontsize(8); a.legend(fontsize=7); a.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(OUT / "characterisation.png"); print("Saved out/characterisation.png")

'''
sub('if __name__ == "__main__":', CMD_CODE + 'if __name__ == "__main__":')
sub('''    elif c == "build": build()''', '''    elif c == "build": build()
    elif c == "sweep": sweep()
    elif c == "characterise": characterise()''')
print("patched OK. Next: python3 aqsense_twin.py make")
