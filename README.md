# AQSENSE - Analog Mains Power Quality Sentinel

A **microcontroller-free** mains monitor built from linear ICs and simulated end-to-end in LTspice.
It watches two things at once:

* **Voltage health** - four-level LED bar graph, an under/over-voltage buzzer, and a fault memory (sample-and-hold).
* **Frequency drift** - detects when the mains leaves a 49-51 Hz window and lights LOW / OK / HIGH LEDs.

Mini-project for the *Linear Integrated Circuits (LIC)* course, NIT Goa (ECE).

> **Status:** design verified in simulation (LTspice 26.1.1). Hardware build and trim calibration are not done yet.
> See [Known limitations](#known-limitations) and [Calibration findings](#calibration-findings) for what the simulation shows is still off.

---

## Contents
1. [Specifications](#specifications)
2. [System overview](#system-overview)
3. [Repository layout](#repository-layout)
4. [Design and results](#design-and-results)
   * [Power supply](#1-power-supply) · [Voltage channel](#2-voltage-channel) · [Buzzer gate](#3-buzzer-gate) · [Sample-and-hold](#4-sample-and-hold-fault-memory)
   * [Frequency channel](#5-frequency-channel) · [Integration](#6-integration-one-mains-source)
5. [Verification summary](#verification-summary)
6. [Debugging log](#debugging-log)
7. [Calibration findings](#calibration-findings)
8. [Known limitations](#known-limitations)
9. [Bill of materials](#bill-of-materials)
10. [Reproducing the simulations](#reproducing-the-simulations)
11. [Future work](#future-work)

---

## Specifications

| Parameter | Value |
|---|---|
| Regulated rail | 9 V (LM7809) |
| Voltage thresholds (design) | 180 V, 200 V, 240 V, 260 V |
| Voltage alarms | buzzer below 180 V and above 260 V |
| Buzzer | 555 astable, about 980 Hz |
| Nominal frequency / window | 50 Hz, 49-51 Hz (+/-1 Hz) |
| Frequency-to-voltage gain | 46.5 mV/Hz (simulated) |
| Frequency flags | LOW below 49 Hz, HIGH above 51 Hz, OK in between |
| Controller | none - comparators, 555 timers, op-amps only |

**Simulation mains convention.** The mains source `V1` uses `Vpk = 0.074 x V_rms`
(so `Vpk = 17.48` is about 236 V rms). This is a scaling used for the simulation; the schematic's
rectifier input is already the scaled level.

## System overview

```mermaid
flowchart LR
  M[Mains] --> BR["Bridge + 1000 uF"]
  BR --> REG["LM7809<br/>9 V rail"]
  BR --> DIV["22k / 10k divider<br/>VSENSE"]
  DIV --> CMP["4x LM339 comparators<br/>(resistor-ladder references)"]
  CMP --> LED["LED bar graph"]
  CMP --> OR["OR gate<br/>under / over voltage"]
  OR --> BUZ["555 astable buzzer"]
  DIV --> SH["Sample-and-hold<br/>fault memory"]
  CMP --> SH
  M --> ATT["Attenuator 0.0286x"] --> SCH["Schmitt trigger<br/>LM339"]
  SCH --> MONO["555 monostable<br/>5.17 ms"]
  MONO --> LPF["2nd-order low-pass<br/>LM324, 3.4 Hz"]
  LPF --> WIN["Window comparator<br/>2.282 - 2.374 V"]
  WIN --> FLED["LOW / OK / HIGH LEDs"]
```

## Repository layout

```
.
├── README.md                  <- this report
├── docs/
│   ├── measurements.md        <- every measured number (tables)
│   └── img/                   <- simulation plots and summary figures
├── simulation/
│   ├── aqsense_full.cir       <- final integrated netlist
│   ├── bode.cir               <- filter frequency-response test
│   ├── test_directives.md     <- the .step / .meas / PWL snippets used for each test
│   └── models/README.md       <- which SPICE models are needed and where they come from
├── scripts/make_plots.py      <- regenerates the summary figures
└── LICENSE
```

---

## Design and results

### 1. Power supply
Full-wave bridge (D1-D4) into C1 = 1000 uF with a 470 ohm dummy load, then an LM7809.
From the earlier PSU phase: output 9.000 V flat with under 5 uV ripple, stable across a
180-260 V mains sweep. (The 1.17 V `Vrip_min` seen in later logs is only the start-up ramp of the rail.)

### 2. Voltage channel
The unregulated bus is divided by R3/R4 (22 kohm / 10 kohm, ratio 0.3125) to give **VSENSE**.
Four LM339 comparators compare VSENSE against a **resistor ladder** off the 9 V rail
(0.5 mA, 18 kohm total), so the references track the rail.

| Comparator | Ladder tap | Reference | Design threshold |
|---|---|---|---|
| COMP1 | V2 (R41 = 7210) | 3.605 V | 180 V |
| COMP2 | V4 (+R40 = 914) | 4.062 V | 200 V |
| COMP3 | V3 (+R39 = 1822) | 4.973 V | 240 V |
| COMP4 | V5 (+R38 = 914, R37 = 7140 to rail) | 5.430 V | 260 V |

Each output has a 10 kohm pull-up (LM339 outputs are open-collector) and an LED to the rail through
470 ohm, so the **LED bar fills as mains rises**: LED1 on above 180 V ... LED4 on above 260 V.

![Voltage channel sweep](docs/img/summary_voltage_sweep.png)

*Sweep from 175 to 265 V rms. Each comparator is fully HIGH well below its threshold, fully LOW above it,
and toggles in a band around it. Raw numbers: [`docs/measurements.md`](docs/measurements.md).*

### 3. Buzzer gate
`D5`/`D6` OR the two alarm signals: COMP1 output (HIGH when mains is below 180 V) and COMP4_INV
(HIGH when mains is above 260 V). The OR output drives the RESET pin of a 555 astable
(R16 = 1 kohm, R17 = 6.8 kohm, C3 = 100 nF, about 980 Hz).

**Bug found and fixed.** With R15 = 10 kohm the 555's RESET pin sourced about 0.4 mA and lifted the gate
to 3.85 V even with both alarms inactive, so the buzzer was never gated off. R15 = **1 kohm** gives 0.40 V
(silent) in the normal range and 1.12 V in the fault state (sounding). Details in
[`docs/measurements.md`](docs/measurements.md#buzzer-gate-r15-sweep).

### 4. Sample-and-hold fault memory
A behavioural CD4066-style switch (`U7`) connects a buffered copy of VSENSE to a 1 uF hold capacitor
**while COMP4_INV is HIGH** (over-voltage). When the fault clears the switch opens and the capacitor holds
the last value, buffered by U10 to `SH_OUT`.

Test: VSENSE forced from 4.0 V up to 6.5 V and back down to 3.0 V.

![S&H hold test](docs/img/sh_hold_test.png)

SH_OUT follows VSENSE during the fault, then stays at **5.431 V** while VSENSE falls to 3 V;
droop was 0.7 mV over 75 ms. *Note:* it stores the voltage at the moment the fault clears (the 260 V
threshold level), not the fault peak. A peak detector would be needed to record the peak.

### 5. Frequency channel

Signal chain: **sine -> Schmitt trigger -> 555 monostable -> low-pass filter -> window comparator**.
Every pulse has a fixed width, so the *average* of the pulse train is proportional to pulse rate,
which is proportional to frequency.

#### 5.1 Schmitt trigger (LM339)
AC-coupled input (C5 = 1 uF, R22 = 4.7 kohm) biased from a dedicated, bypassed 4.5 V node `VBIAS_S`
(R24 = R25 = 2.2 kohm, C7 = 10 uF). Positive feedback R20 = 10 kohm / R21 = 150 kohm gives about
+/-0.27 V of hysteresis (switching at about 4.2 V and 4.8 V). C6 = 100 pF from the + node to ground
keeps the LM339 macromodel numerically stable.

![Schmitt trigger](docs/img/schmitt_working.png)

#### 5.2 Monostable (555)
C8 = 10 nF with R26 = 10 kohm turns each falling edge into a short trigger; D7 clips the positive spike.
R27 = 47 kohm and C10 = 100 nF set the pulse width, `1.1 x R x C = 5.17 ms`. Measured: **5.165 ms**.
At 50 Hz the 9 V pulse train averages 9 V x 5.165 ms x 50 Hz = 2.33 V.

![Monostable](docs/img/monostable_trigger_and_pulse.png)

#### 5.3 Low-pass filter (LM324, Sallen-Key)
Unity-gain 2nd-order filter, R28 = R29 = 100 kohm, C11 = 0.33 uF (to ground), C12 = 0.68 uF (feedback).
Analytically `f0 = 3.36 Hz`, `Q = 0.72`, `-46.9 dB` at 50 Hz, which leaves about 19 mV of ripple
on the DC output. The simulated Bode plot agrees (0 dB passband, -40 dB/decade).

| Analytic | Simulated |
|---|---|
| ![analytic](docs/img/filter_bode_analytic.png) | ![simulated](docs/img/filter_bode_simulated.png) |

The solid line is gain, the dotted line is phase. *(A first run with 0 V DC on the input showed a false
-6 dB passband because the op-amp sat at its rail; the real input averages about 2.3 V, and the test file
uses a 2.3 V DC bias.)*

![FREQ_V at 50 Hz](docs/img/freq_v_filter_50hz.png)

#### 5.4 Window comparator and OK logic
Two LM339 comparators compare FREQ_V with a second ladder: **2.374 V** (51 Hz) and **2.282 V** (49 Hz).
`FREQ_HI` goes LOW above 2.374 V and `FREQ_LO` goes LOW below 2.282 V. LEDs sit on those outputs.
A third comparator makes the **OK** LED: a diode-AND of FREQ_HI and FREQ_LO is compared with V_MID,
so the OK LED lights only when neither flag is active.

The converter is linear at 46.5 mV/Hz and the window thresholds land on 49 Hz and 51 Hz:

![Frequency transfer](docs/img/summary_freq_transfer.png)

50 Hz (OK; separate test source, first run). FREQ_V, FREQ_HI and FREQ_LO settle after the start-up transient:

![50 Hz](docs/img/window_50hz.png)

| 47 Hz (LOW flag) | 53 Hz (HIGH flag) |
|---|---|
| ![47 Hz](docs/img/window_47hz.png) | ![53 Hz](docs/img/window_53hz.png) |

| 49.5 Hz (OK) | 50.5 Hz (OK) |
|---|---|
| ![49.5 Hz](docs/img/window_49p5hz.png) | ![50.5 Hz](docs/img/window_50p5hz.png) |

FREQ_OK_N (the OK LED driver, LOW = lit) at 50 Hz, start-up and steady state:

| First 200 ms | Full run |
|---|---|
| ![OK start-up](docs/img/ok_led_startup.png) | ![OK steady state](docs/img/ok_led_steady_state.png) |

### 6. Integration (one mains source)
Both channels are fed from the single mains source `V1`; the frequency channel gets it through
`B_SENSE = 0.0286 x V(mains)`, which gives 0.5 V peak at `Vpk = 17.48`.

| 50 Hz | 47 Hz | 53 Hz |
|---|---|---|
| ![50 Hz](docs/img/integrated_50hz.png) | ![47 Hz](docs/img/integrated_47hz.png) | ![53 Hz](docs/img/integrated_53hz.png) |

*Traces: FREQ_OK_N (red), FREQ_V (cyan), SENSE_IN (magenta), OR_OUT buzzer gate (grey).*
FREQ_V settles at about 2.33 / 2.19 / 2.47 V (read from the plots), OR_OUT stays at 0.4 V so the
buzzer is silent at normal voltage, and the frequency flags classify correctly. The 53 Hz log reports
`fv_avg` = 2.4677 V, identical to the earlier separate-source run.

---

## Verification summary

| Block | Test | Result |
|---|---|---|
| Reference ladders | six taps vs. targets | within 0.5 mV |
| Voltage comparators | mains sweep 175-265 V | switch in the expected order, with offset (see calibration) |
| Buzzer gate | R15 sweep at 236 V and 284 V | silent at normal, sounding in fault with R15 = 1 kohm |
| Sample-and-hold | forced VSENSE ramp | holds 5.431 V, droop 0.7 mV / 75 ms |
| Schmitt trigger | 50 Hz input | clean 50 Hz square wave |
| Monostable | all frequencies | 5.165 ms pulse |
| Filter | Bode (analytic + simulated) | 0 dB passband, -46.9 dB at 50 Hz |
| Frequency window | 47, 49.5, 50, 50.5, 53 Hz | all classified correctly |
| Integration | 50, 47, 53 Hz, single mains source | all correct |

---

## Debugging log

Problems met while building this, and how they were resolved.

| Problem | Cause | Fix |
|---|---|---|
| No generic LM339 / LM324 / LM7809 / CD4066 in LTspice | not in the standard library | vendor macromodels + custom `.asy` symbols with matching pin order |
| Probes pointed at the wrong node after edits | LTspice renumbers unnamed `Nxxx` nets | explicit `F4` labels on every node used in `.meas` |
| Schmitt solver stalled at about 3.3 ms ("tolerance relaxed" thousands of times) | positive feedback on the LM339 macromodel with no damping | C6 = 100 pF from the + node to ground, `gmin=1e-9`, `reltol=0.01`, capped time step |
| Schmitt output stuck HIGH | its bias came from `V_MID`, a 5 kohm divider with no bypass, which moved with the signal | separate stiff `VBIAS_S` divider with 10 uF |
| Buzzer never gated off | 555 RESET sources about 0.4 mA into a 10 kohm pulldown (3.85 V) | R15 = 1 kohm |
| Filter output dead | U13 supply pins swapped (V+ on ground) | corrected the pin wiring |
| Bode plot showed -6 dB | 0 V DC input pinned the op-amp to its rail | 2.3 V DC bias on the AC source |
| Long runs and stalled sweeps | LM339/LM324 macromodels converge slowly near switching points | shorter `.tran`, forced-node tests, patience (a full sweep takes about 8 minutes) |

![Schmitt solver stall](docs/img/debug_schmitt_solver_stall.png)

*The simulation dying at 3.3 ms before the damping capacitor was added.*

---

## Calibration findings

* **Voltage thresholds sit about 4-7 V above the design values.** The 50 % points of the comparators
  in the sweep are at roughly 184, 207, 247 and 267 V rms against designed 180, 200, 240 and 260 V
  (about 2-3 %). The offset is consistent across all four, which suggests the rectifier drops and ripple
  were not fully included in the divider calculation. **This is a hypothesis, not yet confirmed.**
  Hardware fix: trim the R3/R4 divider with a trimpot, or re-derive it with measured drops.
* **Soft thresholds.** Each comparator changes over a band of roughly +/-10 V of mains instead of at a point.
  This is consistent with ripple on VSENSE (not measured directly). A capacitor on VSENSE would sharpen it.
* **Frequency thresholds.** The 49 Hz and 51 Hz references can be set to about 1 mV (about 0.02 Hz); in
  hardware these become a trimpot.

## Known limitations

* **Start-up flicker.** The frequency flags flicker for about 0.2 s (up to about 0.45 s near the thresholds)
  while the filter settles. A short power-up inhibit would hide it.
* **Ripple near the limits.** About +/-15-20 mV of ripple on FREQ_V (about 0.4 Hz) means the LEDs can flicker within
  about 0.4 Hz of 49 and 51 Hz. 49.5 and 50.5 Hz were clean.
* **Fault memory stores the threshold, not the peak.**
* **Buzzer-gate margin in hardware.** The fault-state gate level is only about 1.1 V against a 555 reset
  threshold of roughly 0.7 V (datasheet range about 0.3-1.0 V). Lower R19 and R5 from 10 kohm to
  about 2.2 kohm for margin. Not simulated.
* **Frequency input amplitude.** The Schmitt needs the AC-coupled signal to clear its +/-0.27 V hysteresis,
  so the frequency channel depends on the mains amplitude. Not yet characterised; a limiting amplifier would remove it.
* **Non-standard resistor values** (e.g. 13252, 4564, 7140 ohm) are simulation-exact; hardware needs
  trimpots or E96 values with fine adjustment.
* **Simulation only.** The LM339/LM324 are vendor macromodels; real parts will differ in offset,
  slew and output saturation.

## Bill of materials

| Ref | Part | Value |
|---|---|---|
| D1-D4 | rectifier diodes | generic (`standard.dio`) |
| C1 / R1 | bulk capacitor / dummy load | 1000 uF / 470 ohm |
| U1 | regulator | LM7809 |
| R3, R4 | VSENSE divider | 22 kohm, 10 kohm |
| R37-R41 | voltage reference ladder | 7140, 914, 1822, 914, 7210 ohm |
| U2-U5 | comparators | LM339 |
| R5-R8 | comparator pull-ups | 10 kohm |
| R9-R12, LED1-LED4 | LED bar | 470 ohm, LEDs |
| R13, R14, U6 | V_MID divider, inverter | 10 kohm each, LM339 |
| D5, D6, R15 | buzzer OR gate | diodes, 1 kohm |
| U8, R16, R17, C2, C3, R18 | buzzer 555 astable | NE555, 1 k, 6.8 k, 10 nF, 100 nF, 100 ohm |
| R19 | COMP4_INV pull-up | 10 kohm |
| U9, U10, U7, C4 | S&H buffers, switch, hold cap | LM324 x2, CD4066-type, 1 uF |
| C5, R20-R25, C6, C7, U11, R23 | Schmitt trigger and bias | 1 uF, 10 k, 150 k, 4.7 k, 2.2 k x2, 100 pF, 10 uF, LM339, 10 k |
| U12, R26, D7, C8, C9, R27, C10 | monostable | NE555, 10 k, diode, 10 nF, 10 nF, 47 k, 100 nF |
| U13, R28, R29, C11, C12 | low-pass filter | LM324, 100 k x2, 0.33 uF, 0.68 uF |
| R42-R44 | frequency reference ladder | 13252, 184, 4564 ohm |
| U14, U15, R30, R31, R32, R33, D8, D9 | window comparators and LEDs | LM339 x2, 10 k x2, 470 ohm x2, LEDs |
| R34, D10, D11, U16, R35, R36, D12 | OK logic and LED | 10 k, diodes, LM339, 10 k, 470 ohm, LED |

## Reproducing the simulations

1. Install [LTspice](https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html) (tested on 26.1.1).
2. Put the models listed in [`simulation/models/README.md`](simulation/models/README.md) next to the netlist.
3. Open `simulation/aqsense_full.cir` and run it (about 45 s for 1 s of simulated time).
4. For each test, add the directives from [`simulation/test_directives.md`](simulation/test_directives.md).
5. `python scripts/make_plots.py` regenerates the three summary figures (needs `numpy` and `matplotlib`).

## Future work

* Build on a breadboard, then compare with the simulation.
* Add trimpots for the voltage divider and both frequency references, and recalibrate.
* Add a VSENSE filter capacitor and a power-up inhibit for the frequency flags.
* Replace the sample-and-hold with a peak-hold if a true fault-peak record is wanted.
* Add a limiting stage ahead of the Schmitt trigger.

## Author

Kartikey - Electronics and Communication Engineering, NIT Goa.
Kathan - Electronics and Communication Engineering, NIT Goa.

## Software demonstration layer: AQSENSE Facility Twin
`twin/` connects the LTspice simulation outputs to a virtual-facility application. Python writes the mains stimulus,
LTspice (unchanged circuit) produces the outputs, and a browser dashboard decodes the recorded node voltages.
Simulation only. See `twin/TWIN_GUIDE.md`.

### Facility Twin integration findings (LTspice 26.1.1)
* **Measured trip points** (ramps over 0.5 s, applied mains from the recorded stimulus): LED1 about 182-183 V, LED2 about 202-204 V,
  LED3 about 243-245 V, LED4 about 267-268 V; frequency flags about 49 and 51 Hz (dynamic values, lag-affected).
* **Fault memory does not capture in the integrated circuit.** With R15 = 1 kohm, COMP4_INV reaches only 1.77 V during over-voltage, below the
  sample-and-hold switch threshold (Th = 2.16 V, fully on near 5 V), so SH_OUT stays at about 0.6 V while VSENSE peaks at 5.8 V.
  The earlier hold test used a forced VSENSE and did not expose this.
* **What-if (simulation only):** R19 = 680 ohm raises COMP4_INV to 5.79 V and the memory captures 5.45 V (the threshold level, not the peak).
  Trade-off: about 13 mA through the LM339 output in normal state. A buffered, dedicated control line for U7 would be a cleaner fix.
  Not verified on hardware.
* **Start-up:** BUZZER_OUT chirps while the rails settle; the application inhibits the first 0.9 s.
