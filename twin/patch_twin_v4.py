#!/usr/bin/env python3
"""Run inside aqsense/twin:  python3 patch_twin_v4.py
1) python3 aqsense_twin.py make --tweak N name1 name2 ...   regenerates ONLY the named scenarios with numerical solver options
   (tweak 1: Tmaxstep 40u | 2: + gear integration | 3: + tiny shunts). The circuit is not changed.
2) s7_vramp: shorter dwell near the under-voltage region (180 V, 0.2 s) after the 178 V hold stalled the solver
3) sweep / characterise skip incomplete (stalled) runs instead of printing nonsense
4) bug fix: crossings() dropped a crossing when a 20 ms bin sat at exactly 50 % duty (affected the trip tables from extract too)"""
from pathlib import Path
A = "aqsense_twin.py"
def sub(old, new):
    s = Path(A).read_text(encoding="utf-8"); assert old in s, "pattern not found:\n" + old[:100]
    Path(A).write_text(s.replace(old, new, 1), encoding="utf-8")

sub("def make():", '''TWEAKS = {1: ["* solver tweak 1: Tmaxstep 40u (numerical only, circuit unchanged)"],
          2: ["* solver tweak 2: Tmaxstep 40u + gear integration (numerical only, circuit unchanged)", ".options method=gear"],
          3: ["* solver tweak 3: Tmaxstep 40u + tiny shunts (numerical only, circuit unchanged)", ".options cshunt=1e-15 gshunt=1e-12"]}

def make(names=None, tweak=0):''')
sub('''    for name, sc in SCN.items():
        r = WORK / f"{name}.raw"''', '''    for name, sc in SCN.items():
        if names and name not in names: continue
        r = WORK / f"{name}.raw"''')
sub('''line = f".tran 0 {sc['end']} 0 50u"''', '''line = f".tran 0 {sc['end']} 0 {'40u' if tweak else '50u'}"''')
sub('''SAVE + sc.get("xsave", [])), ".options plotwinsize=0", ".end"]''', '''SAVE + sc.get("xsave", [])), ".options plotwinsize=0"] + TWEAKS.get(tweak, []) + [".end"]''')
sub('''print(f"  wrote scenarios/{name}.cir  (+ .pwl, {sc['end']} s of simulated time)")''',
    '''print(f"  wrote scenarios/{name}.cir  (+ .pwl, {sc['end']} s of simulated time" + (f", solver tweak {tweak})" if tweak else ")"))''')
sub('''    if c == "make": make()''', '''    if c == "make":
        _a = a[1:]; make([x for x in _a if x in SCN], int(_a[_a.index("--tweak") + 1]) if "--tweak" in _a else 0)''')

sub("SCN = {k: SCN[k] for k in _ORDER + [k for k in SCN if k not in _ORDER]}", '''SCN = {k: SCN[k] for k in _ORDER + [k for k in SCN if k not in _ORDER]}
SCN["s7_vramp"] = dict(title="Characterisation: voltage ramp", end=14.8, ramp=(2.3, 8.55, 14.8),
    desc="Slow ramp 180 V to 290 V and back (18.3 V/s) to measure the comparator trip points.",
    pts=[(0, 236, 50), (1.6, 236, 50), (2.1, 180, 50), (2.3, 180, 50), (8.3, 290, 50), (8.8, 290, 50), (14.8, 180, 50)],
    marks=[(0, .9, "Power-up"), (.9, 1.6, "Healthy"), (1.6, 2.3, "Step down to 180 V"), (2.3, 8.55, "Slow ramp up, 18.3 V/s"),
           (8.55, 14.8, "Slow ramp down, 18.3 V/s")])''')

sub('''        tr = load(f); t = tr["time"]; W = lambda k, a, b: tr[f"v({k})"][(t >= a) & (t < b)]''',
    '''        tr = load(f); t = tr["time"]; W = lambda k, a, b: tr[f"v({k})"][(t >= a) & (t < b)]
        if t[-1] < 5.45: print(f"  {n}: incomplete, stopped at {t[-1]:.2f} s of 5.5 s, skipped"); continue''')
sub('''loaded.append((name, ak, unit, sigs, d))''', '''loaded.append((name, ak, unit, sigs, d))
        if d["end"] < r1 - 0.3: print(f"  WARNING {name}: data stops at {d['end']:.1f} s, before the ramp ends at {r1} s (solver stalled?)")''')
sub("""    s = np.sign(x - .5); return [(i, "on/asserted" if s[i] > 0 else "off/released") for i in range(max(lo, 1), len(x)) if s[i] != s[i - 1] and s[i] != 0 and s[i-1] != 0]""",
    """    s = np.where(np.asarray(x, float) > .5, 1, -1); return [(i, "on/asserted" if s[i] > 0 else "off/released") for i in range(max(lo, 1), len(x)) if s[i] != s[i - 1]]""")
print("patched OK")
