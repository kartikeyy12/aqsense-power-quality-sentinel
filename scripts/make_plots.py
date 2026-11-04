"""Regenerates the summary figures in docs/img from the measured values in docs/measurements.md."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

out = Path(__file__).resolve().parent.parent / "docs" / "img"

# ---- 1. Frequency channel transfer: FREQ_V vs mains frequency -------------
f  = np.array([47, 49.5, 50, 50.5, 53])
fv = np.array([2.1887, 2.3048, 2.3282, 2.3515, 2.4677])
slope, icpt = np.polyfit(f, fv, 1)
lo, hi = 2.282, 2.374
fig, ax = plt.subplots(figsize=(7, 4.2))
ax.axhspan(lo, hi, color="tab:green", alpha=0.15, label="OK window (2.282 - 2.374 V)")
xx = np.linspace(46.5, 53.5, 50)
ax.plot(xx, slope * xx + icpt, "--", color="gray", label=f"linear fit: {slope*1000:.1f} mV/Hz")
ax.plot(f, fv, "o", color="tab:blue", label="simulated FREQ_V (avg 0.7-1.0 s)")
ax.axvline(49, color="k", lw=0.6, ls=":"); ax.axvline(51, color="k", lw=0.6, ls=":")
ax.set_xlabel("Mains frequency (Hz)"); ax.set_ylabel("FREQ_V (V)")
ax.set_title("Frequency channel: DC output vs. mains frequency")
ax.grid(alpha=0.3); ax.legend(fontsize=8, loc="upper left")
fig.tight_layout(); fig.savefig(out / "summary_freq_transfer.png", dpi=150); plt.close(fig)

# ---- 2. Voltage channel: comparator behaviour vs. mains -------------------
mains = np.array([175, 185, 195, 205, 235, 245, 255, 265])
vs = np.array([3.40313, 3.61569, 3.83828, 4.05186, 4.72943, 4.94392, 5.16484, 5.38015])
c = {
 "COMP1": [8.18255, 4.01198, 0.13596, 0.13513, 0.13513, 0.13513, 0.13513, 0.13513],
 "COMP2": [8.95861, 8.99993, 8.99992, 4.85538, 0.13513, 0.13513, 0.13513, 0.13513],
 "COMP3": [8.95861, 8.99993, 8.99992, 8.99991, 8.99989, 5.14805, 1.31206, 0.13514],
 "COMP4": [8.95848, 8.99980, 8.99979, 8.99977, 8.99976, 8.99975, 8.99974, 5.41231],
}
design = {"COMP1": 180, "COMP2": 200, "COMP3": 240, "COMP4": 260}
fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
a1.plot(mains, vs, "o-", color="tab:blue", label="VSENSE (average)")
for name, v in zip(["COMP1", "COMP2", "COMP3", "COMP4"], [3.605, 4.062, 4.973, 5.430]):
    a1.axhline(v, color="gray", lw=0.7, ls="--")
    a1.text(175.5, v + 0.02, f"{name} ref {v:.3f} V", fontsize=7, color="gray")
a1.set_ylabel("VSENSE (V)"); a1.grid(alpha=0.3); a1.legend(fontsize=8, loc="lower right")
a1.set_title("Voltage channel: sense node and comparator outputs")
for name, vals in c.items():
    frac = (np.array(vals) - 0.135) / (9.0 - 0.135)
    l, = a2.plot(mains, np.clip(frac, 0, 1) * 100, "o-", label=name)
    a2.axvline(design[name], color=l.get_color(), lw=0.8, ls=":")
a2.set_xlabel("Mains (V rms, Vpk = 0.074 x V)"); a2.set_ylabel("Time output is HIGH (%)")
a2.grid(alpha=0.3); a2.legend(fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.18))
a2.text(176, 8, "dotted = design thresholds (180/200/240/260 V)", fontsize=7)
fig.tight_layout(); fig.savefig(out / "summary_voltage_sweep.png", dpi=150); plt.close(fig)

# ---- 3. Analytic Bode of the Sallen-Key filter ----------------------------
R1 = R2 = 100e3; C_gnd = 0.33e-6; C_fb = 0.68e-6
w0 = 1 / np.sqrt(R1 * R2 * C_gnd * C_fb)
Q = np.sqrt(R1 * R2 * C_gnd * C_fb) / (C_gnd * (R1 + R2))
fr = np.logspace(-1, 3, 500); s = 1j * 2 * np.pi * fr
H = 1 / (1 + s * C_gnd * (R1 + R2) + s**2 * R1 * R2 * C_gnd * C_fb)
g50 = 20 * np.log10(abs(1 / (1 + 1j*2*np.pi*50*C_gnd*(R1+R2) - (2*np.pi*50)**2 * R1*R2*C_gnd*C_fb)))
fig, ax = plt.subplots(figsize=(7, 4))
ax.semilogx(fr, 20 * np.log10(abs(H)))
ax.axvline(50, color="tab:red", ls=":"); ax.plot([50], [g50], "o", color="tab:red")
ax.annotate(f"50 Hz: {g50:.1f} dB", (50, g50), (60, g50 + 15), fontsize=8, color="tab:red")
ax.set_ylim(-110, 5); ax.grid(which="both", alpha=0.3)
ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Gain (dB)")
ax.set_title(f"Sallen-Key low-pass (analytic): f0 = {w0/2/np.pi:.2f} Hz, Q = {Q:.2f}")
fig.tight_layout(); fig.savefig(out / "filter_bode_analytic.png", dpi=150); plt.close(fig)
print(f"f0={w0/2/np.pi:.3f} Hz  Q={Q:.3f}  gain@50Hz={g50:.2f} dB  slope={slope*1000:.2f} mV/Hz")
