# AQSENSE Facility Twin - guide

A PC application built **around** the unchanged analog circuit. LTspice simulates AQSENSE; Python carries the
simulated node voltages into a software "virtual facility" whose equipment reacts to AQSENSE's own flags.
**Simulation only** - no real-time monitoring, no hardware, no real electrical protection is claimed.

```
 Python writes mains stimulus          LTspice (your aqsense_full.cir,         Python reads the results         Browser app
 (V and f vs time, .pwl)  ───────────► unchanged circuit; only V1 swapped) ───► .raw -> 20 ms bins, decode ───► AQSENSE_Twin.html
        make                                        run                      extract (+ build)         LEDs, buzzer, facility,
                                                                                                        event log, scope
```
Detection happens **only** in the circuit. Python never compares VSENSE to 180 V, never windows the frequency, never
gates the buzzer. It only (1) generates the *input* waveform and (2) turns the *output* node voltages into logic levels
(mid-rail of the recorded VREG_OUT), using the polarities below.

## Signal map (verified against aqsense_full.cir)
| Circuit node | Meaning | Decoded by software as |
|---|---|---|
| COMP1..4_OUT | + = reference, - = VSENSE; LED sits to the rail, so **LED lit = output LOW** | LED_k lit when node LOW (duty per 20 ms) |
| COMP1_OUT HIGH | mains below ~184 V (also feeds buzzer OR gate via D6) | UNDER-VOLTAGE |
| COMP4_OUT LOW | mains above ~265 V (LED4 lit; COMP4_INV feeds the OR gate via D5 but is a diode-loaded node, so it is not decoded) | OVER-VOLTAGE |
| BUZZER_OUT | 555 output ~980 Hz, only while OR_OUT high | buzzer active if swing > mid-rail inside a bin |
| FREQ_LO / FREQ_HI | **active-LOW**: FREQ_LO low = f < 49 Hz, FREQ_HI low = f > 51 Hz | LOW / HIGH frequency |
| FREQ_OK_N | active-LOW: low = OK LED lit | FREQ OK |
| VSENSE, FREQ_V | analog measurements | calibrated read-outs (README sweeps: 46.5 mV/Hz etc.) |
| SH_OUT | fault memory | shown as-is; "latched" value logged |
| MAINS_A - MAINS_B | the stimulus as LTspice saw it | **ground truth** (applied V_rms-equiv and frequency via zero-crossings) |

## Quick start (Windows, or WSL - see the WSL note below)
```
pip install numpy                      # only dependency for the bridge
cd aqsense-power-quality-sentinel\twin
python aqsense_twin.py make            # writes scenarios\*.cir + *.pwl  (models are taken from ..\simulation)
python aqsense_twin.py run             # parallel LTspice batch runs (or open each .cir in LTspice and press Run)
python aqsense_twin.py extract         # reads scenarios\*.raw -> data\*.json, prints measured trip points
python aqsense_twin.py build           # -> out\AQSENSE_Twin.html  (double-click, Chrome/Edge)
```
* LTspice not found automatically? `set AQSENSE_LTSPICE=C:\Users\<you>\AppData\Local\Programs\ADI\LTspice\LTspice.exe`
* **Time the first run:** run only `python aqsense_twin.py run s1_normal` first (4 s simulated). Your README says ~45 s per simulated
  second, so all four scenarios (about 33 s simulated) take roughly 25 min sequentially, less in parallel. Start them early.
* If `.raw` reading fails: in LTspice use *File > Export data as text* for the .raw plot of the saved nodes, save as `scenarios\<name>.txt`
  (or `.csv`); `extract` reads that too. `python aqsense_twin.py inspect scenarios\s1_normal.raw` lists what is inside.
* **UI preview before the real runs finish:** `python tests\make_fixture.py` then `extract`, `build`. The page shows a red
  *SYNTHETIC TEST DATA* banner. `make` deletes these fake files automatically. Never demo from them.

## What the application does
* **Replay panel** - LED bar, LOW/OK/HIGH LEDs, buzzer, read-outs, all from LTspice traces. LED brightness = fraction of time the node
  was low, so comparator chatter near a threshold is visible.
* **Facility supervisor (software)** - reacts to AQSENSE flags after a 0.9 s start-up inhibit and a 100 ms persistence qualifier:
  | AQSENSE flag | Response |
  |---|---|
  | UV (COMP1_OUT high) or OV (COMP4_INV high) | servers to UPS, conveyor trips, HVAC lock-out, lights 40 % / off |
  | LED1 only (low band) | conveyor derated to 70 %, lights 70 % |
  | LED3 on (high band) | lights 85 % |
  | FREQ_LO or FREQ_HI | conveyor trips |
  | FREQ_V implausible (< 44 Hz equiv.) | "signal lost" warning, frequency flag not trusted |
  Restore after 1 s of healthy supply. The conveyor speed readout = 1500 rpm x FREQ_V-derived frequency / 50.
* **Exposure table** - seconds each asset spent out of spec (applied mains outside 180-260 V / 49-51 Hz, from the recorded stimulus)
  with the supervisor vs ignoring AQSENSE. It includes the circuit's own latency and threshold offset, so it is an honest score.
* **Event log** - each line names the circuit node that triggered it. On over-voltage it prints the SH_OUT value the circuit kept next to the
  peak the *software* logged from VSENSE, which makes the "memory stores the threshold, not the peak" limitation visible.

## Scenarios
| # | File | Story | What to watch |
|---|---|---|---|
| 1 | s1_normal | 232-241 V, 49.85-50.15 Hz | no alarms, all assets running |
| 2 | s2_voltage | 236 -> 195 -> 178 -> 236 -> 255 -> 284 -> 236 V | LED bar steps down/up, UV buzzer, OV buzzer, SH_OUT latch, servers on UPS |
| 3 | s3_frequency | 50 -> 47.5 -> 50 -> 52.5 -> 50.4 Hz | LOW then HIGH LED, conveyor trips, **FREQ_V lag ~0.3-0.5 s**, 50.4 Hz stays OK |
| 4 | s4_generator | V and f sag together, recover, then V and f surge | compound fault, every asset reacts |
Edit `SCN` in `aqsense_twin.py` (list of time/volt/Hz points) to add your own, then `make`, `run`, `extract`, `build`.

## Known limitations (show them, they are findings)
1. **Trip points sit above design** (README: ~184/207/247/267 V). `extract` prints measured trip points from the real data
   next to the design values.
2. **Start-up** - flags flicker ~0.2-0.45 s; the app inhibits the first 0.9 s (README's suggested power-up inhibit).
3. **Ripple near 49/51 Hz** - +/-0.4 Hz of chatter is possible; shown through LED duty, tamed by the 100 ms qualifier.
4. **Fault memory** stores the threshold level, not the peak.
5. **Deep sag may blind the frequency channel.** From the netlist, the Schmitt trigger (about +/-0.3 V hysteresis) sees about 0.31 V peak at
   175-178 V mains (0.0286 x Vpk x 0.83 AC-coupling attenuation). If FREQ_V collapses during the sag, the app reports
   "SIGNAL LOST?" rather than a false LOW alarm. If it happens it is a real result of your circuit: report it.
6. Mains in LTspice is scaled (Vpk = 0.074 x V_rms). Scenario durations are compressed (seconds, not minutes) - 1x playback = simulated time.
7. LTspice runs are slow, so playback is pre-computed replay, not live co-simulation.

## WSL note
Python steps (`make`, `extract`, `build`) run fine in WSL. LTspice is a Windows program, so for `run` open
`scenarios\*.cir` from Windows (`cd twin/scenarios && explorer.exe .`) and press Run. Open `out/AQSENSE_Twin.html` with
`explorer.exe out` or `wslview out/AQSENSE_Twin.html`.
