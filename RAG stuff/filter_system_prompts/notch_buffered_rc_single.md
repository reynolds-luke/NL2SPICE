# Notch Filter, Buffered Single-Stage Twin-T RC (buffered_rc_single)

This document explains how a buffered single-stage passive RC Twin-T notch filter works, how the input buffer prevents source loading from shifting the notch frequency, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An ideal unity-gain input buffer (VCVS) drives the Twin-T network, ensuring the source impedance does not load or detune the filter. The notch frequency and depth are then determined solely by the R and C components inside the Twin-T.

**Use this topology when:**
- The signal source has high or variable output impedance.
- Precise, source-independent notch frequency is needed.
- A single notch stage is sufficient (one rejection frequency).

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

RTA1  VBUF  nta    {R}
RTA2  nta   out    {R}
CTAS1 nta   0      {C}
CTAS2 nta   0      {C}

CTB1  VBUF  ntb    {C}
CTB2  ntb   out    {C}
RTBS1 ntb   0      {R}
RTBS2 ntb   0      {R}

EOUT VOUT  0     out  0  1
.end
```

---

## Transfer Function

The input buffer makes the Twin-T response independent of source impedance. The transfer function from VBUF to `out` is:

$$H(s) = \frac{1 + \tau^2 s^2}{1 + 4\tau s + \tau^2 s^2}, \quad \tau = RC$$

**Notch frequency:** `f₀ = 1/(2π·R·C)`

**−3 dB passband edges:**
- `f_L ≈ 0.2361 × f₀`
- `f_H ≈ 4.2361 × f₀`

**Q ≈ 0.25** (passive Twin-T, wide notch).

---

## Key Equations

Same as `notch_rc_single`:

1. `f0 = 1 / (2π · R · C)`
2. `C = 1 / (2π · f0 · R)`
3. `f_L ≈ 0.2361 × f0`
4. `f_H ≈ 4.2361 × f0`
5. `BW ≈ 4 × f0`
6. `Q ≈ 0.25`

---

## Design Procedure

**Step 1 — Identify f₀.**

**Step 2 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 3 — Compute C = 1 / (2π · f₀ · R).** Check C ∈ [1 nF, 100 nF].

**Step 4 — Write netlist:**  
1. `EBUF VBUF 0 VIN 0 1`
2. Resistive arm from VBUF
3. Capacitive arm from VBUF
4. `EOUT VOUT 0 out 0 1`

---

## Worked Example 1

**Specification:** Notch filter, f₀ = 2 kHz, high-Z source, passband must recover to −3 dB by 4.236× and 0.2361× of f₀.

**Step 1:** f₀ = 2 000 Hz.

**Step 2:** R = 10 kΩ.

**Step 3:** C = 1/(2π × 2000 × 10000) = 7.958 nF.

**Step 4:** f_L ≈ 472 Hz, f_H ≈ 8 472 Hz.

```spice
* Single-stage passive RC notch filter (Twin-T) with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Twin-T notch section
* Resistive arm
RTA1 VBUF  nta    10k
RTA2 nta   out    10k
CTAS1 nta  0      7.958n
CTAS2 nta  0      7.958n

* Capacitive arm
CTB1 VBUF  ntb    7.958n
CTB2 ntb   out    7.958n
RTBS1 ntb  0      10k
RTBS2 ntb  0      10k

EOUT VOUT  0     out  0  1
.end
```

---

## Worked Example 2

**Specification:** Notch filter, f₀ = 10 kHz, high-Z source.

**Step 1:** f₀ = 10 000 Hz.

**Step 2:** R = 5 kΩ (smaller R to keep C ≥ 1 nF at higher frequency).

**Step 3:** C = 1/(2π × 10000 × 5000) = 3.183 nF ✓.

```spice
* Single-stage passive RC notch filter (Twin-T) with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Twin-T notch section
* Resistive arm
RTA1 VBUF  nta    5k
RTA2 nta   out    5k
CTAS1 nta  0      3.183n
CTAS2 nta  0      3.183n

* Capacitive arm
CTB1 VBUF  ntb    3.183n
CTB2 ntb   out    3.183n
RTBS1 ntb  0      5k
RTBS2 ntb  0      5k

EOUT VOUT  0     out  0  1
.end
```

---

## Worked Example 3

**Specification:** Notch filter, f₀ = 60 Hz (power-line rejection), high-Z electret microphone source.

**Step 1:** f₀ = 60 Hz.

**Step 2:** R = 40 kΩ (large R to keep C in range).

**Step 3:** C = 1/(2π × 60 × 40000) = 66.31 nF ✓ (< 100 nF).

**f_L ≈ 14.2 Hz, f_H ≈ 254.2 Hz.**

```spice
* Single-stage passive RC notch filter (Twin-T) with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Twin-T notch section
* Resistive arm
RTA1 VBUF  nta    40k
RTA2 nta   out    40k
CTAS1 nta  0      66.31n
CTAS2 nta  0      66.31n

* Capacitive arm
CTB1 VBUF  ntb    66.31n
CTB2 ntb   out    66.31n
RTBS1 ntb  0      40k
RTBS2 ntb  0      40k

EOUT VOUT  0     out  0  1
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Notch frequency shifted | EBUF missing; source loads Twin-T | Add `EBUF VBUF 0 VIN 0 1`; arms start from VBUF not VIN |
| No notch | Arms don't connect to same node `out` | Verify RTA2 and CTB2 both terminate at `out` |
| VOUT always 0 | EOUT missing | Add `EOUT VOUT 0 out 0 1` |
| Notch depth poor | Component mismatch (different R or C for each arm) | Use identical values: same R for RTA1,RTA2,RTBS1,RTBS2; same C for CTAS1,CTAS2,CTB1,CTB2 |
| C > 100 nF | Low f₀ or large R | Reduce R toward 10 kΩ |
| C < 1 nF | High f₀ or small R | Increase R toward 100 kΩ |
| EBUF error | Wrong syntax | `EBUF VBUF 0 VIN 0 1` — six tokens |
