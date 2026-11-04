# Measured results (LTspice 26.1.1)

All values come from `.meas` lines in the simulator log unless marked *read from plot*.
Mains convention: `Vpk = 0.074 x V_rms`, so `Vpk = 17.48` is about 236 V rms.

## Reference ladders (unloaded, 0.5 mA, 9 V rail)
| Tap | Target (V) | Measured (V) |
|---|---|---|
| V2 (COMP1) | 3.605 | 3.6054 |
| V4 (COMP2) | 4.062 | 4.0624 |
| V3 (COMP3) | 4.973 | 4.9733 |
| V5 (COMP4) | 5.430 | 5.4303 |
| V7 (FREQ high) | 2.374 | 2.3743 |
| V8 (FREQ low)  | 2.282 | 2.2823 |

## Voltage-channel sweep (`.step`, 0.1-0.2 s averages)
| Mains (V rms) | VSENSE avg (V) | COMP1 | COMP2 | COMP3 | COMP4 | OR_OUT / buzzer gate (V) |
|---|---|---|---|---|---|---|
| 175 | 3.403 | 8.18 | 8.96 | 8.96 | 8.96 | 7.55 |
| 185 | 3.616 | 4.01 | 9.00 | 9.00 | 9.00 | 5.64 |
| 195 | 3.838 | 0.136 | 9.00 | 9.00 | 9.00 | 3.85 (*) |
| 205 | 4.052 | 0.135 | 4.86 | 9.00 | 9.00 | 3.85 (*) |
| 235 | 4.729 | 0.135 | 0.135 | 9.00 | 9.00 | 3.85 (*) |
| 245 | 4.944 | 0.135 | 0.135 | 5.15 | 9.00 | 3.85 (*) |
| 255 | 5.165 | 0.135 | 0.135 | 1.31 | 9.00 | 3.85 (*) |
| 265 | 5.380 | 0.135 | 0.135 | 0.135 | 5.41 | 4.74 |

(*) With R15 = 10 kOhm, before the buzzer-gate fix. See "Buzzer gate" below.
Averages between about 0.14 V (LOW) and 9 V (HIGH) mean the output toggles during the window.

## Buzzer gate (R15 sweep)
| R15 | Mains | OR_OUT avg (V) | Buzzer peak (V) | Result |
|---|---|---|---|---|
| 10 k | 236 V | 3.850 | 8.50 | buzzing at normal voltage (bug) |
| 1.5 k | 236 V | 0.600 | 0.00005 | silent |
| **1 k** | 236 V | **0.400** | **0.00005** | **silent** |
| 10 k | 284 V | 6.043 | 8.49 | buzzing |
| 1.5 k | 284 V | 1.611 | 8.50 | buzzing |
| **1 k** | 284 V | **1.123** | **8.50** | **buzzing** |

The silent-state voltage equals 0.4 mA x R15: the 555 RESET pin sources about 0.4 mA.

## Sample-and-hold (hold mode)
VSENSE forced 4.0 V -> 6.5 V -> 3.0 V (PWL). Fault line = 5.43 V.
| Quantity | Value |
|---|---|
| `held_a` (SH_OUT at 120 ms, 8 ms after fault cleared) | 5.4314 V |
| `held_b` (SH_OUT at 195 ms) | 5.4307 V |
| Droop over 75 ms | 0.7 mV (about 9 mV/s) |

## Frequency channel (mains-derived, `fv_avg` over 0.7-1.0 s)
| Frequency (Hz) | FREQ_V (V) | Flag |
|---|---|---|
| 47   | 2.1887 | LOW |
| 49.5 | 2.3048 | OK |
| 50   | 2.3282 | OK |
| 50.5 | 2.3515 | OK |
| 53   | 2.4677 | HIGH |

Linear fit: 46.5 mV/Hz. Monostable pulse width `pw` = 5.165 ms at every frequency.
Integrated runs (one mains source feeding both channels): 50 Hz, 47 Hz and 53 Hz classified
correctly (FREQ_V *read from plot*: about 2.33 / 2.19 / 2.47 V); 53 Hz log: `fv_avg` = 2.4677 V.

## Filter (analytic, from component values)
f0 = 3.36 Hz, Q = 0.72, gain at 50 Hz = -46.9 dB, predicted ripple from the 4.16 V fundamental of
the pulse train = about 19 mV. Simulated Bode (`docs/img/filter_bode_simulated.png`) shows 0 dB
passband and -40 dB/decade roll-off.
