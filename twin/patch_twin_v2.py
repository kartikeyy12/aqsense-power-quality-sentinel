#!/usr/bin/env python3
"""Run inside aqsense/twin:  python3 patch_twin_v2.py
1) dashboard reports fault-memory capture truthfully (captured / NOT captured + control-line level)
2) buzzer sound muted during the 0.9 s power-up inhibit; conveyor speed follows the APPLIED frequency (physics), not the sensor estimate
3) adds optional scenario s5_memfix: same circuit with R19 = 680 ohm, clearly labelled as a design what-if"""
from pathlib import Path
def sub(path, old, new):
    p = Path(path); s = p.read_text(encoding="utf-8"); assert old in s, f"{path}: pattern not found:\n{old[:80]}"
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
A, H = "aqsense_twin.py", "dashboard_template.html"
# ---- Python bridge
sub(A, ' "s4_generator": dict(', ''' "s5_memfix": dict(title="5 - WHAT-IF: fault memory with R19 = 680 ohm", end=5.5, rep={"R19": "680"},
   mod="R19 10k -> 680 ohm (design what-if, NOT the original circuit)",
   desc="Same circuit except R19: tests whether a stronger COMP4_INV level lets the sample-and-hold switch close.",
   pts=[(0,236,50),(1.6,236,50),(2.1,284,50),(3.5,284,50),(4.1,236,50),(5.5,236,50)],
   marks=[(0,.9,"Power-up"),(.9,1.6,"Healthy"),(1.6,3.5,"Surge to 284 V"),(3.5,5.5,"Recovery - does the memory hold?")]),
 "s4_generator": dict(''')
sub(A, '''            if u.startswith("v1 "):''', '''            p = line.split()
            if p and p[0].upper() in sc.get("rep", {}):                       # what-if component change (labelled in the netlist)
                p[-1] = sc["rep"][p[0].upper()]; line = " ".join(p) + "  ; WHAT-IF change, not the original value"
            elif u.startswith("v1 "):''')
sub(A, '''    vs, sh, fv, orv = (B(G(k)).mean(1) for k in ("vsense", "sh_out", "freq_v", "or_out"))''',
       '''    vs, sh, fv, orv, ci = (B(G(k)).mean(1) for k in ("vsense", "sh_out", "freq_v", "or_out", "comp4_inv"))''')
sub(A, '''ovev.append(dict(t0=run0 * BIN, t1=i * BIN, pk=pk,''', '''ovev.append(dict(t0=run0 * BIN, t1=i * BIN, cap=bool(sh[j] >= 4.3), ctl=float(ci[run0:i].max()), pk=pk,''')
sub(A, '''created=datetime.datetime''', '''mod=sc.get("mod", ""), created=datetime.datetime''')
sub(A, '''print(f"     OV event {e['t0']:.2f}-{e['t1']:.2f}s: software-logged peak VSENSE {e['pk']:.2f} V (~{e['pkm']:.0f} V) | SH_OUT latched {e['sh']:.2f} V (~{e['shm']:.0f} V)")''',
       '''print(f"     OV event {e['t0']:.2f}-{e['t1']:.2f}s: peak VSENSE {e['pk']:.2f} V (~{e['pkm']:.0f} V) | SH_OUT held {e['sh']:.2f} V | memory {'CAPTURED' if e['cap'] else 'NOT captured'} | COMP4_INV reached {e['ctl']:.2f} V")''')
# ---- dashboard
sub(H, '''c:"wn",
  m:`Fault memory SH_OUT = ${f2(e.sh)} V (~${f2(e.shm,0)} V): the circuit kept the threshold. Software-logged peak from VSENSE: ${f2(e.pk)} V (~${f2(e.pkm,0)} V)`}));''',
       '''c:e.cap?"wn":"er",
  m:(e.cap?`Fault memory captured SH_OUT = ${f2(e.sh)} V (~${f2(e.shm,0)} V): the threshold level, not the peak.`
   :`Fault memory did NOT capture: SH_OUT stayed at ${f2(e.sh)} V. Its switch control (COMP4_INV) only reached ${f2(e.ctl)} V; the analog gate needs about 5 V.`)
   +` Software-logged peak from VSENSE: ${f2(e.pk)} V (~${f2(e.pkm,0)} V)`}));''')
sub(H, '''playing?.04:0''', '''playing&&s.t[i]>=INH?.04:0''')
sub(H, '''const tgt=($("act").checked&&a.mot)?0:1500*S.fe[idx]/50*''', '''const fq=S.fa[idx]==null?S.fe[idx]:S.fa[idx];const tgt=($("act").checked&&a.mot)?0:1500*fq/50*''')
sub(H, '''$("src").className=sy?"syn":"";''', '''$("src").className=sy?"syn":S.mod?"mod":"";''')
sub(H, '''(extracted ${S.created})`;''', '''(extracted ${S.created})`+(S.mod?" | CIRCUIT MODIFIED: "+S.mod:"");''')
sub(H, '''#src.syn{''', '''#src.mod{color:var(--wn);border-color:var(--wn);font-weight:700}#src.syn{''')
print("patched OK. Next: python3 aqsense_twin.py make   (creates s5_memfix.cir), run s5 in LTspice, then extract + build")
