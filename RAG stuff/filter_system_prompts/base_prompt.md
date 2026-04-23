# SPICE Netlist Format Reference

This document defines the SPICE netlist conventions used across all filter topology explainers in this project. All netlists must conform to these rules.

---

## Mandatory Nodes

| Node | Role |
|------|------|
| `VIN` | Signal input (driven by AC source) |
| `VOUT` | Filter output |
| `0` | Ground reference |

Internal nodes use short descriptive lowercase names: `n1`, `n2`, `mid`, `buf`, `nh1`, `nh2`, `nl1`, `nl2`, `nta`, `ntb`, etc. Never reuse a node name for a different net.

---

## AC Source

Every netlist must include exactly one AC voltage source connected between `VIN` and ground:

```
V1   VIN   0     AC 1
```

---

## Component Syntax

```
R<name>  <node+>  <node->  <value>      Resistor
C<name>  <node+>  <node->  <value>      Capacitor
L<name>  <node+>  <node->  <value>      Inductor
E<name>  <out+>   0        <in+>  0  <gain>   VCVS (ideal op-amp model)
```

**Value suffixes:** `p` (pico), `n` (nano), `u` (micro), `m` (milli), `k` (kilo), `meg` (mega).

Examples:
```
R1   VIN   n1   10k
C1   n1    0    15.9n
EBUF buf   0    VIN  0  1
```

---

## Modelling Active Devices

**Never** use semiconductor primitives (`Q`, `M`, `J`, `D`) or library subcircuits. Model all active behaviour with VCVS E-elements:

- **Unity-gain voltage follower (op-amp buffer):**
  ```
  EBUF  buf   0   VIN  0  1
  ```
  The output node `buf` tracks `VIN` with zero output impedance.

- **Amplifier with gain G:**
  ```
  EAMP  out   0   in   0  <G>
  ```

- **Differential input:**
  ```
  EDIFF out   0   vp   vn  <G>
  ```

---

## Netlist Order

```
* Optional one-line description comment
V1   VIN   0     AC 1
[optional input buffer]
[component definitions — R, C, L, E]
.end
```

**Rules:**
- The first line may be a `*` comment (it becomes the SPICE title and is ignored by the simulator).
- No dot commands other than `.end`.
- No `.AC`, `.TRAN`, `.OP`, `.MODEL`, `.LIB`, `.SUBCKT`, `.INCLUDE`.
- No semiconductor primitives.
- No inline `;` comments (use `*` lines only).

---

## Component Ranges (this project)

| Component | Range |
|-----------|-------|
| Resistors | 1 kΩ – 100 kΩ |
| Capacitors | 1 nF – 100 nF |

Stay within these ranges unless the target frequency makes it unavoidable.

---

## Minimal Valid Netlist (example)

```spice
* Single-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   VOUT   10k
C1   VOUT  0      15.9n
.end
```

---

## Troubleshooting Checklist

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Simulator parse error | Wrong node count, missing value, bad suffix | Check every component line has `name node+ node- value` |
| No `.end` | Missing terminator | Add `.end` as the last line |
| Simulation won't converge | Floating node, short circuit | Check every node is connected to at least two elements |
| Cutoff frequency wrong | Wrong R or C value | Recalculate: `fc = 1 / (2π R C)`, adjust R or C |
| Output voltage is zero | VOUT shorted or wrong node name | Verify the output node is named `VOUT` exactly |
| Buffer output is wrong | VCVS syntax error | Format: `EBUF out 0 in 0 1` — exactly five fields after the name |
