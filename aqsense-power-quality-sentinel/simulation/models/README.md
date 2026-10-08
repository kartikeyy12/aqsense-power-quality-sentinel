# Models required

This project uses behavioural / vendor SPICE models that are **not** committed here
(licences differ). Place them in this folder (or next to the netlist) before simulating.

| File | Used for | Where it comes from |
|---|---|---|
| `LM7809.lib` | U1, 9 V regulator | Vendor SPICE macromodel (manufacturer product page) |
| `LM339.lib`  | U2-U6, U11, U14-U16 comparators | Vendor SPICE macromodel |
| `LM324.lib`  | U9, U10, U13 op-amps | Vendor SPICE macromodel |
| `AnalogGate.lib` | U7, CD4066-style analog switch | Behavioural CD4066-equivalent analog switch subcircuit (pin order `+CTRL -CTRL IN OUT`) |
| `NE555.sub`  | U8, U12 timers | Ships with LTspice (`Misc > NE555`, idealised 555) |

LTspice has no generic LM339 / LM324 / LM7809 / CD4066 parts, so each needs a subcircuit
**and** a matching `.asy` symbol whose pin order follows the comment header of the `.lib`.
Check the pin order in the netlist comments (`;§pnba ...`) if a model misbehaves.
