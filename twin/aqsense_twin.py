#!/usr/bin/env python3
"""AQSENSE Facility Twin - LTspice -> software bridge.

  python aqsense_twin.py make       write scenario netlists + mains stimulus (.pwl) next to aqsense_full.cir models
  python aqsense_twin.py run        batch-run LTspice on every scenario (or open the .cir files in LTspice and press Run)
  python aqsense_twin.py extract    read the LTspice .raw (or exported .csv/.txt) -> data/*.json
  python aqsense_twin.py build      embed data into out/AQSENSE_Twin.html
  python aqsense_twin.py all        make + run + extract + build
  python aqsense_twin.py inspect F  list the variables/points in a .raw/.csv file

DESIGN RULE: Python only (a) writes the *mains stimulus* that goes INTO LTspice and (b) reads the node voltages that
come OUT of LTspice. Every detection decision (comparators, window, buzzer gate, fault memory) happens in the
LTspice circuit. Nothing here re-implements it.
"""
import os, sys, json, time, subprocess, datetime
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
SIM = (HERE.parent / "simulation") if (HERE.parent / "simulation").exists() else HERE / "simulation"
WORK, DATA, OUT = HERE / "scenarios", HERE / "data", HERE / "out"

VPK_PER_VRMS = 0.074        # README: simulation mains convention Vpk = 0.074 x V_rms
T_INHIBIT = 0.9             # s, start-up transient (README: flags flicker 0.2-0.45 s)
BIN = 0.020                 # s, analysis bin = exactly 1 mains cycle -> 50/100 Hz ripple averages out
DT = 50e-6                  # s, uniform resample grid (= .tran Tmaxstep)
SAVE = ["vreg_out", "vsense", "sh_out", "freq_v", "comp1_out", "comp2_out", "comp3_out", "comp4_out",
        "comp4_inv", "or_out", "buzzer_out", "freq_hi", "freq_lo", "freq_ok_n", "mains_a", "mains_b"]
# Readout calibration = the README's own measured sweeps (docs/measurements.md). Used ONLY for numeric displays.
CAL_V = ([175, 185, 195, 205, 235, 245, 255, 265], [3.40313, 3.61569, 3.83828, 4.05186, 4.72943, 4.94392, 5.16484, 5.38015])
CAL_F = ([47, 49.5, 50, 50.5, 53], [2.1887, 2.3048, 2.3282, 2.3515, 2.4677])
DESIGN = {"l1": 180, "l2": 200, "l3": 240, "l4": 260}

# ---- scenarios: (t[s], mains V_rms-equivalent, frequency Hz) corner points, linearly interpolated -------------------
SCN = {
 "s1_normal": dict(title="Normal operation", end=4.0,
   desc="Healthy mains with small drift (232-241 V, 49.85-50.15 Hz). Proves there are no false alarms.",
   pts=[(0,236,50),(1.5,236,50),(2.5,241,50.15),(3.3,232,49.85),(4,236,50)],
   marks=[(0,.9,"Power-up: circuit settling, flags inhibited"),(.9,4,"Healthy mains")]),
 "s2_voltage": dict(title="Voltage sag and surge", end=10.7,
   desc="236 V -> 195 V -> 178 V (under-voltage) -> 236 V -> 255 V -> 284 V (over-voltage) -> 236 V.",
   pts=[(0,236,50),(1.6,236,50),(2.1,195,50),(3,195,50),(3.5,178,50),(4.6,178,50),(5.2,236,50),(6,236,50),
        (6.5,255,50),(7.2,255,50),(7.7,284,50),(8.9,284,50),(9.5,236,50),(10.7,236,50)],
   marks=[(0,.9,"Power-up"),(.9,1.6,"Healthy"),(1.6,3,"Sag to 195 V"),(3,4.6,"Deep sag to 178 V"),(4.6,6,"Recovery"),
          (6,7.2,"High: 255 V"),(7.2,8.9,"Surge: 284 V"),(8.9,10.7,"Recovery, memory holds")]),
 "s3_frequency": dict(title="Frequency drift", end=8.2,
   desc="50 Hz -> 47.5 Hz (LOW) -> 50 Hz -> 52.5 Hz (HIGH) -> 50.4 Hz at constant 236 V.",
   pts=[(0,236,50),(1.6,236,50),(2,236,47.5),(3.4,236,47.5),(3.8,236,50),(4.8,236,50),(5.2,236,52.5),(6.6,236,52.5),
        (7,236,50.4),(8.2,236,50.4)],
   marks=[(0,.9,"Power-up"),(.9,1.6,"Healthy"),(1.6,3.4,"Under-frequency 47.5 Hz"),(3.4,4.8,"Recovery"),
          (4.8,6.6,"Over-frequency 52.5 Hz"),(6.6,8.2,"Recovery (50.4 Hz, inside window)")]),
 "s5_memfix": dict(title="What-if: fault memory, R19 = 680 ohm", end=5.5, rep={"R19": "680"},
   mod="R19 10k to 680 ohm. Design what-if, not the original circuit.",
   desc="Same circuit except R19: tests whether a stronger COMP4_INV level lets the sample-and-hold switch close.",
   pts=[(0,236,50),(1.6,236,50),(2.1,284,50),(3.5,284,50),(4.1,236,50),(5.5,236,50)],
   marks=[(0,.9,"Power-up"),(.9,1.6,"Healthy"),(1.6,3.5,"Surge to 284 V"),(3.5,5.5,"Recovery, does the memory hold?")]),
 "s4_generator": dict(title="Generator overload and load rejection", end=10.0,
   desc="Islanded generator: sag AND slow-down together, recovery, then load rejection: surge AND over-speed.",
   pts=[(0,236,50),(1.6,236,50),(3,178,47.8),(4.4,178,47.8),(5.4,236,50),(6.4,236,50),(6.9,282,52.4),(8.2,282,52.4),
        (9,236,50),(10,236,50)],
   marks=[(0,.9,"Power-up"),(.9,1.6,"Healthy"),(1.6,4.4,"Generator overload: V and f fall"),(4.4,6.4,"Recovery"),
          (6.4,8.2,"Load rejection: V and f rise"),(8.2,10,"Recovery")]),
}

# ---- v3 scenarios: R19 sweep, buffered memory control, characterisation ramps -----------------------------
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
SCN["s7_vramp"] = dict(title="Characterisation: voltage ramp", end=14.8, ramp=(2.3, 8.55, 14.8),
    desc="Slow ramp 180 V to 290 V and back (18.3 V/s) to measure the comparator trip points.",
    pts=[(0, 236, 50), (1.6, 236, 50), (2.1, 180, 50), (2.3, 180, 50), (8.3, 290, 50), (8.8, 290, 50), (14.8, 180, 50)],
    marks=[(0, .9, "Power-up"), (.9, 1.6, "Healthy"), (1.6, 2.3, "Step down to 180 V"), (2.3, 8.55, "Slow ramp up, 18.3 V/s"),
           (8.55, 14.8, "Slow ramp down, 18.3 V/s")])

# ---------------------------------------------------------------------------------------------- make
def mains_wave(sc, dt=200e-6):
    t = np.arange(0, sc["end"] + dt, dt); p = np.array(sc["pts"], float)
    V, F = np.interp(t, p[:, 0], p[:, 1]), np.interp(t, p[:, 0], p[:, 2])
    ph = 2 * np.pi * np.concatenate([[0], np.cumsum((F[1:] + F[:-1]) / 2 * dt)])   # phase-continuous
    return t, VPK_PER_VRMS * V * np.sin(ph)

TWEAKS = {1: ["* solver tweak 1: Tmaxstep 40u (numerical only, circuit unchanged)"],
          2: ["* solver tweak 2: Tmaxstep 40u + gear integration (numerical only, circuit unchanged)", ".options method=gear"],
          3: ["* solver tweak 3: Tmaxstep 40u + tiny shunts (numerical only, circuit unchanged)", ".options cshunt=1e-15 gshunt=1e-12"]}

def make(names=None, tweak=0):
    WORK.mkdir(exist_ok=True)
    import shutil                                  # models next to the netlists, as in the project README (no absolute paths)
    for m in list(SIM.glob("*.lib")) + list(SIM.glob("*.sub")): shutil.copy(m, WORK / m.name)
    src = (SIM / "aqsense_full.cir").read_bytes().decode("latin-1")      # latin-1 round-trip keeps the '§' bytes intact
    for name, sc in SCN.items():
        if names and name not in names: continue
        r = WORK / f"{name}.raw"                     # never let SYNTHETIC test data survive into a real run
        if r.exists() and any("SYNTHETIC" in r.read_bytes()[:600].decode(e, "ignore") for e in ("utf-16-le", "latin-1")): r.unlink()
        t, v = mains_wave(sc)
        (WORK / f"{name}.pwl").write_text("".join(f"{a:.6f} {b:.5f}\n" for a, b in zip(t, v)))
        out = [f"* Scenario '{name}' generated from aqsense_full.cir. ONLY V1 (stimulus), .tran, .meas and .save were changed."]
        for line in src.splitlines():
            u = line.strip().lower()
            p = line.split()
            if p and p[0].upper() in sc.get("rep", {}):                       # what-if component change (labelled in the netlist)
                p[-1] = sc["rep"][p[0].upper()]; line = " ".join(p) + "  ; WHAT-IF change, not the original value"
            elif p and p[0].upper().startswith("X") and any(p[0].upper().endswith(k) for k in sc.get("swap", {})):
                k = next(k for k in sc["swap"] if p[0].upper().endswith(k)); p[sc["swap"][k][0]] = sc["swap"][k][1]
                line = " ".join(p) + "  ; WHAT-IF: node changed"
            elif u.startswith("v1 "):
                line = f"V1 MAINS_A MAINS_B PWL file={name}.pwl"
            elif u.startswith(".tran"):
                line = f".tran 0 {sc['end']} 0 {'40u' if tweak else '50u'}"
            elif u.startswith(".meas") or u == ".end":
                continue
            out.append(line)
        out += sc.get("add", [])
        out += [".save " + " ".join(f"V({n})" for n in SAVE + sc.get("xsave", [])), ".options plotwinsize=0"] + TWEAKS.get(tweak, []) + [".end"]
        (WORK / f"{name}.cir").write_bytes("\n".join(out).encode("latin-1"))
        print(f"  wrote scenarios/{name}.cir  (+ .pwl, {sc['end']} s of simulated time" + (f", solver tweak {tweak})" if tweak else ")"))
    print("Next: python aqsense_twin.py run   (or open each scenarios/*.cir in LTspice and press Run)")

# ---------------------------------------------------------------------------------------------- run
def find_ltspice():
    c = [os.environ.get("AQSENSE_LTSPICE"), os.path.expanduser(r"~\AppData\Local\Programs\ADI\LTspice\LTspice.exe"),
         r"C:\Program Files\ADI\LTspice\LTspice.exe", r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe",
         "/Applications/LTspice.app/Contents/MacOS/LTspice"]
    return next((p for p in c if p and os.path.exists(p)), None)

def is_wsl(): return "microsoft" in Path("/proc/version").read_text().lower() if Path("/proc/version").exists() else False

def run(only=None):
    if is_wsl():
        win = subprocess.run(["wslpath", "-w", str(WORK)], capture_output=True, text=True).stdout.strip()
        sys.exit("WSL detected: run the simulations with Windows LTspice (batch launch from WSL is unreliable).\n"
                 f"  1. In this folder run:  cd {WORK} && explorer.exe .     (Windows path: {win})\n"
                 "  2. Open each scenario .cir in LTspice and press Run (several windows can run at once).\n"
                 "  3. A .raw file appears next to each .cir. Then: python aqsense_twin.py extract")
    exe = find_ltspice()
    if not exe:
        sys.exit("LTspice not found. Set AQSENSE_LTSPICE=<path to LTspice.exe>, or open scenarios/*.cir in LTspice and press Run "
                 "(a .raw file appears next to each .cir).")
    names = [n for n in SCN if not only or n in only]
    t0 = time.time(); procs = {n: subprocess.Popen([exe, "-Run", "-b", f"{n}.cir"], cwd=WORK) for n in names}
    print(f"Started {len(procs)} LTspice batch runs in parallel ({exe}). Each can take several minutes...")
    for n, p in procs.items():
        p.wait(); raw = WORK / f"{n}.raw"; log = WORK / f"{n}.log"; warn = 0
        if log.exists():
            b = log.read_bytes(); txt = b.decode("utf-16", "ignore") if b[:2] in (b"\xff\xfe", b"\xfe\xff") or b[1:2] == b"\0" else b.decode("latin-1")
            warn = txt.count("tolerance relaxed")
        print(f"  {n}: {'OK' if raw.exists() else 'NO .raw!'}  ({time.time()-t0:.0f} s elapsed)" + (f"  WARNING: solver relaxed tolerance {warn}x - check {n}.log" if warn else ""))

# ---------------------------------------------------------------------------------------------- readers
def read_raw(path):
    """Minimal reader for LTspice binary/ASCII .raw transient files (no extra packages)."""
    b = Path(path).read_bytes(); u16 = len(b) > 1 and b[1] == 0
    enc = "utf-16-le" if u16 else "latin-1"; ch = 2 if u16 else 1
    for key in ("Binary:", "Values:"):
        k = b.find(key.encode(enc))
        if k >= 0: break
    else: raise ValueError("no Binary:/Values: marker - not an LTspice transient .raw?")
    head = b[:k].decode(enc, "ignore"); pos = k + len(key) * ch
    while b[pos:pos + ch].decode(enc, "ignore") in ("\r", "\n"): pos += ch
    hd, names, inv = {}, [], False
    for ln in head.splitlines():
        if inv:
            p = ln.split()
            if len(p) >= 3 and p[0].isdigit(): names.append(p[1].lower())
        elif ln.startswith("Variables:"): inv = True
        elif ":" in ln: a, c = ln.split(":", 1); hd[a.strip()] = c.strip()
    nv, npts, flags = len(names), int(hd.get("No. Points", 0)), hd.get("Flags", "")
    if "fastaccess" in flags.lower(): raise ValueError("Fast Access .raw not supported - re-run the simulation (do not use -FastAccess)")
    if key == "Values:":
        a = np.array(b[pos:].decode(enc, "ignore").split(), float).reshape(-1, nv + 1)[:, 1:]; cols = a.T
    else:
        dbl = "double" in flags.lower(); rec = 8 * nv if dbl else 8 + 4 * (nv - 1)
        cnt = min(npts, (len(b) - pos) // rec) if npts else (len(b) - pos) // rec
        if dbl: cols = np.frombuffer(b, "<f8", cnt * nv, pos).reshape(cnt, nv).T
        else:
            arr = np.frombuffer(b, np.dtype([("t", "<f8"), ("v", "<f4", (nv - 1,))]), cnt, pos)
            cols = np.vstack([arr["t"][None, :], arr["v"].T.astype(float)])
    tr = {n: np.asarray(c, float) for n, c in zip(names, cols)}; tr["time"] = np.abs(tr[names[0]])
    tr["_title"] = hd.get("Title", ""); return tr

def read_text(path):
    """LTspice 'File > Export data as text' (tab/comma separated, first line = names)."""
    ln = Path(path).read_text(errors="ignore").splitlines(); sep = "\t" if "\t" in ln[0] else ","
    names = [h.strip().lower() for h in ln[0].split(sep)]
    a = np.array([[float(x) for x in l.split(sep)] for l in ln[1:] if l.strip()])
    tr = {n: a[:, i] for i, n in enumerate(names)}; tr["time"] = tr[names[0]]; tr["_title"] = ""; return tr

def load(path):
    tr = read_raw(path) if str(path).lower().endswith(".raw") else read_text(path)
    t = tr["time"]; _, ix = np.unique(t, return_index=True)
    return {k: (v[ix] if isinstance(v, np.ndarray) else v) for k, v in tr.items()}

def inspect(path):
    tr = load(path); t = tr["time"]
    print(f"{path}\n title: {tr['_title']!r}\n points: {len(t)}  t = {t[0]:.4g} .. {t[-1]:.4g} s")
    for k, v in tr.items():
        if k not in ("time", "_title"): print(f"  {k:14s} min {v.min():9.4f}  max {v.max():9.4f}")

# ---------------------------------------------------------------------------------------------- extract
def crossings(x, lo):
    s = np.where(np.asarray(x, float) > .5, 1, -1); return [(i, "on/asserted" if s[i] > 0 else "off/released") for i in range(max(lo, 1), len(x)) if s[i] != s[i - 1]]

def extract(name, path=None):
    sc = SCN[name]
    path = path or next((p for e in (".raw", ".csv", ".txt") for p in [WORK / f"{name}{e}"] if p.exists()), None)
    if not path: sys.exit(f"No data for {name}: expected scenarios/{name}.raw (run LTspice) or .csv/.txt (File>Export data as text).")
    tr = load(path); miss = [k for k in SAVE if f"v({k})" not in tr]
    if miss: sys.exit(f"{path}: missing traces {miss}. Use the generated scenarios/*.cir (they contain the .save line) "
                      "or add these nodes to the plot before exporting.")
    per = int(round(BIN / DT)); Tend = min(sc["end"], tr["time"][-1]); n = int(Tend / BIN)
    if Tend < sc["end"] - .05: print(f"  WARNING {name}: simulation stopped at {Tend:.2f} s of {sc['end']} s (solver abort?)")
    grid = np.arange(n * per) * DT
    G = lambda k: np.interp(grid, tr["time"], tr[f"v({k})"])
    B = lambda x: x.reshape(n, per)
    rail = G("vreg_out"); thr = rail / 2                                   # logic threshold = mid-rail (from LTspice itself)
    low = lambda k: B(G(k) < thr).mean(1)                                 # fraction of the bin the node is LOW
    bz = G("buzzer_out"); bzb = B(bz); buz = ((bzb.max(1) - bzb.min(1)) > thr.reshape(n, per).mean(1)).astype(int)
    vs, sh, fv, orv, ci = (B(G(k)).mean(1) for k in ("vsense", "sh_out", "freq_v", "or_out", "comp4_inv"))
    vm = G("mains_a") - G("mains_b"); vr = (B(vm).max(1) - B(vm).min(1)) / 2 / VPK_PER_VRMS   # applied mains (ground truth)
    zc = np.where(np.signbit(vm[:-1]) & ~np.signbit(vm[1:]))[0]
    tz = grid[zc] - vm[zc] * DT / (vm[zc + 1] - vm[zc]); cen = (np.arange(n) + .5) * BIN
    fa = np.interp(cen, (tz[1:] + tz[:-1]) / 2, 1 / np.diff(tz)) if len(tz) > 2 else np.full(n, np.nan)
    mV, bV = np.polyfit(*CAL_V, 1)[0], np.polyfit(*CAL_V, 1)[1]; mF, bF = np.polyfit(CAL_F[1], CAL_F[0], 1)
    me, fe = (vs - bV) / mV, mF * fv + bF
    d = dict(t=cen, vs=vs, sh=sh, fv=fv, vr=vr, fa=fa, me=me, fe=fe, orv=orv,
             l1=low("comp1_out"), l2=low("comp2_out"), l3=low("comp3_out"), l4=low("comp4_out"),   # LED lit = output LOW
             ov=low("comp4_out"),                                                                # over-voltage flag = HIGH
             bz=buz, fh=low("freq_hi"), fl=low("freq_lo"), fk=low("freq_ok_n"))                      # active-low flags
    lo = int(T_INHIBIT / BIN); trips = []
    for k, dv in DESIGN.items():
        for i, dr in crossings(d[k], lo): trips.append(dict(sig=f"LED{k[1]} ({dv} V design)", dir=dr, applied=float(vr[i]), design=dv))
    for k, dv, nm in (("fl", 49, "FREQ_LO flag"), ("fh", 51, "FREQ_HI flag")):
        for i, dr in crossings(d[k], lo): trips.append(dict(sig=f"{nm} ({dv} Hz design)", dir=dr, applied=float(fa[i]), design=dv))
    ovev, run0 = [], None
    for i in range(lo, n + 1):
        on = i < n and d["ov"][i] > .5
        if on and run0 is None: run0 = i
        if not on and run0 is not None:
            j = min(i + 3, n - 1); pk = float(vs[run0:i].max())
            ovev.append(dict(t0=run0 * BIN, t1=i * BIN, cap=bool(sh[j] >= 4.3), ctl=float(ci[run0:i].max()), pk=pk, pkm=float((pk - bV) / mV), sh=float(sh[j]), shm=float((sh[j] - bV) / mV))); run0 = None
    meta = dict(id=name, title=sc["title"], desc=sc["desc"], marks=sc["marks"], bin=BIN, end=n * BIN, file=Path(path).name,
                src=("synthetic" if "SYNTHETIC" in tr["_title"].upper() else "ltspice"), hdr=tr["_title"],
                mod=sc.get("mod", ""), created=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), trips=trips, ovev=ovev)
    DATA.mkdir(exist_ok=True)
    out = dict(meta, **{k: [None if not np.isfinite(x) else round(float(x), 4) for x in v] for k, v in d.items()})
    (DATA / f"{name}.json").write_text(json.dumps(out)); print(f"  {name}: {n} bins from {Path(path).name} [{meta['src']}]")
    for tp in trips: print(f"     {tp['sig']:30s} {tp['dir']:4s} at applied {tp['applied']:.1f}")
    for e in ovev: print(f"     OV event {e['t0']:.2f}-{e['t1']:.2f}s: peak VSENSE {e['pk']:.2f} V (~{e['pkm']:.0f} V) | SH_OUT held {e['sh']:.2f} V | memory {'CAPTURED' if e['cap'] else 'NOT captured'} | COMP4_INV reached {e['ctl']:.2f} V")

def build():
    files = [DATA / f"{n}.json" for n in SCN if (DATA / f"{n}.json").exists() and not SCN[n].get("hide")]
    if not files: sys.exit("No data/*.json - run extract first.")
    OUT.mkdir(exist_ok=True); tpl = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    js = "[" + ",".join(f.read_text() for f in files) + "]"
    (OUT / "AQSENSE_Twin.html").write_text(tpl.replace("/*__DATA__*/null", js), encoding="utf-8")
    print(f"Built out/AQSENSE_Twin.html with {len(files)} scenario(s). Open it in Chrome/Edge.")

def _find(n):
    return next((WORK / f"{n}{e}" for e in (".raw", ".csv", ".txt") if (WORK / f"{n}{e}").exists()), None)

def sweep():
    """R19 sweep: does the memory capture, does the buzzer still sound, what does the LM339 have to sink?"""
    rows = []
    for lab, r, n in [(f"{r} ohm", r, n) for r, n in SWEEP] + [("buffered", 10000, "s6_bufctl")]:
        f = _find(n)
        if not f: print(f"  {n}: no data yet, skipped"); continue
        tr = load(f); t = tr["time"]; W = lambda k, a, b: tr[f"v({k})"][(t >= a) & (t < b)]
        if t[-1] < 5.45: print(f"  {n}: incomplete, stopped at {t[-1]:.2f} s of 5.5 s, skipped"); continue
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
    (OUT / "r19_sweep.csv").write_text(",".join(keys) + "\n" + "\n".join(",".join(str(x[k]) for k in keys) for x in rows) + "\n")
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
        if d["end"] < r1 - 0.3: print(f"  WARNING {name}: data stops at {d['end']:.1f} s, before the ramp ends at {r1} s (solver stalled?)")
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
    OUT.mkdir(exist_ok=True); (OUT / "characterisation.csv").write_text("\n".join(lines) + "\n")
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

if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]; c = a[0]
    if c == "make":
        _a = a[1:]; make([x for x in _a if x in SCN], int(_a[_a.index("--tweak") + 1]) if "--tweak" in _a else 0)
    elif c == "run": run(a[1:] or None)
    elif c == "extract": [extract(n) for n in SCN if any((WORK / f"{n}{e}").exists() for e in (".raw", ".csv", ".txt"))]
    elif c == "build": build()
    elif c == "sweep": sweep()
    elif c == "characterise": characterise()
    elif c == "inspect": inspect(a[1])
    elif c == "all": make(); run(); [extract(n) for n in SCN]; build()
    else: print(__doc__)
