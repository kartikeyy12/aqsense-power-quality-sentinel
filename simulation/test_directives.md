# Test directives used during verification

Add these as SPICE directives to the schematic (or append to `aqsense_full.cir`) for each test.
Remove them afterwards - several of them override nodes of the real circuit.

## Frequency sweep (one run per frequency)
Change V1 to `SINE(0 {Vpk} <f>)` with f = 47, 49.5, 50, 50.5, 53 and read:
```
.meas TRAN fv_avg AVG V(freq_v) FROM 0.7 TO 1.0
```

## Voltage sweep (8 mains points, ~8 min)
```
.param Vpk=17.48
.step param Vpk list 12.95 13.69 14.43 15.17 17.39 18.13 18.87 19.61
.tran 0 0.2 0 50u
.meas TRAN vs AVG V(vsense) FROM 0.1 TO 0.2
.meas TRAN c1 AVG V(comp1_out) FROM 0.1 TO 0.2
.meas TRAN c2 AVG V(comp2_out) FROM 0.1 TO 0.2
.meas TRAN c3 AVG V(comp3_out) FROM 0.1 TO 0.2
.meas TRAN c4 AVG V(comp4_out) FROM 0.1 TO 0.2
.meas TRAN bz AVG V(or_out)    FROM 0.1 TO 0.2
```
Vpk 12.95 ... 19.61 correspond to 175 ... 265 V rms (Vpk = 0.074 x V rms).

## Sample-and-hold hold-mode test
Forces VSENSE with an ideal PWL source (overrides the divider). Remove afterwards.
```
V_TEST VSENSE 0 PWL(0 4 20m 4 60m 6.5 100m 6.5 140m 3 200m 3)
.tran 0 0.2 0 50u
.meas TRAN held_a FIND V(sh_out) AT 120m
.meas TRAN held_b FIND V(sh_out) AT 195m
```

## Buzzer-gate (R15) check
Make R15 a parameter `{Rr}`, then:
```
.param Rr=10k
.step param Rr list 10k 1.5k 1k
.step param Vpk list 17.48 21
.meas TRAN bz  AVG V(or_out) FROM 0.1 TO 0.2
.meas TRAN bzo MAX V(buzzer_out) FROM 0.1 TO 0.2
```
Vpk 17.48 is about 236 V rms (normal); Vpk 21 is about 284 V rms (over-voltage fault).

## Filter Bode plot
Run `bode.cir` (AC analysis; DC 2.3 V bias on the input).
