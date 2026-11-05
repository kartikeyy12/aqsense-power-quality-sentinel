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

# ---------------------------------------------------------------------------------------------- make
def mains_wave(sc, dt=200e-6):
    t = np.arange(0, sc["end"] + dt, dt); p = np.array(sc["pts"], float)
    V, F = np.interp(t, p[:, 0], p[:, 1]), np.interp(t, p[:, 0], p[:, 2])
    ph = 2 * np.pi * np.concatenate([[0], np.cumsum((F[1:] + F[:-1]) / 2 * dt)])   # phase-continuous
    return t, VPK_PER_VRMS * V * np.sin(ph)

def make():
    WORK.mkdir(exist_ok=True)
    import shutil                                  # models next to the netlists, as in the project README (no absolute paths)
    for m in list(SIM.glob("*.lib")) + list(SIM.glob("*.sub")): shutil.copy(m, WORK / m.name)
    src = (SIM / "aqsense_full.cir").read_bytes().decode("latin-1")      # latin-1 round-trip keeps the '§' bytes intact
    for name, sc in SCN.items():
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
            elif u.startswith("v1 "):
                line = f"V1 MAINS_A MAINS_B PWL file={name}.pwl"
            elif u.startswith(".tran"):
                line = f".tran 0 {sc['end']} 0 50u"
            elif u.startswith(".meas") or u == ".end":
                continue
            out.append(line)
        out += [".save " + " ".join(f"V({n})" for n in SAVE), ".options plotwinsize=0", ".end"]
        (WORK / f"{name}.cir").write_bytes("\n".join(out).encode("latin-1"))
        print(f"  wrote scenarios/{name}.cir  (+ .pwl, {sc['end']} s of simulated time)")
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
    s = np.sign(x - .5); return [(i, "on/asserted" if s[i] > 0 else "off/released") for i in range(max(lo, 1), len(x)) if s[i] != s[i - 1] and s[i] != 0 and s[i-1] != 0]

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
    files = [DATA / f"{n}.json" for n in SCN if (DATA / f"{n}.json").exists()]
    if not files: sys.exit("No data/*.json - run extract first.")
    OUT.mkdir(exist_ok=True); tpl = (HERE / "dashboard_template.html").read_text(encoding="utf-8")
    js = "[" + ",".join(f.read_text() for f in files) + "]"
    (OUT / "AQSENSE_Twin.html").write_text(tpl.replace("/*__DATA__*/null", js), encoding="utf-8")
    print(f"Built out/AQSENSE_Twin.html with {len(files)} scenario(s). Open it in Chrome/Edge.")

if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]; c = a[0]
    if c == "make": make()
    elif c == "run": run(a[1:] or None)
    elif c == "extract": [extract(n) for n in SCN if any((WORK / f"{n}{e}").exists() for e in (".raw", ".csv", ".txt"))]
    elif c == "build": build()
    elif c == "inspect": inspect(a[1])
    elif c == "all": make(); run(); [extract(n) for n in SCN]; build()
    else: print(__doc__)
