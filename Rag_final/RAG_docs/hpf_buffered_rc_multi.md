# High-Pass Filter, Two-Stage Buffered RC (buffered_rc_multi)

This document explains how a two-stage passive RC high-pass filter with an input buffer works, how to size components (including the loading correction), and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An ideal unity-gain input buffer (VCVS) drives two cascaded CR high-pass stages. The input buffer isolates the source, but the two stages are directly connected (no inter-stage buffer), so stage 2 still loads stage 1. The combined response follows the loaded two-stage formula.

**Use this topology when:**
- The source impedance is high or unknown.
- Steeper −40 dB/decade roll-off is needed below fc.
- Source-independent cutoff is critical.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  n1     {C}
R1   n1    0      {R}
C2   n1    VOUT   {C}
R2   VOUT  0      {R}
.end
```

---

## Transfer Function

Same denominator as the loaded two-stage HPF (rc_multi):

$$H(s) = \frac{\tau^2 s^2}{1 + 3\tau s + \tau^2 s^2}, \quad \tau = RC$$

**Combined −3 dB:**

$$f_{3dB} = 2.672 \times f_{c,\text{stage}} = 2.672 \times \frac{1}{2\pi RC}$$

**Design equation** (target fc → stage components):

$$f_{c,\text{stage}} = 0.3743 \times f_c$$

$$C = \frac{2.672}{2\pi \cdot f_c \cdot R}$$

**Asymptotic roll-off:** −40 dB/decade below fc.

---

## Key Equations

1. `fc_stage = 1 / (2π · R · C)`
2. `fc_combined = 2.672 · fc_stage`
3. `C = 2.672 / (2π · fc · R)`  (design equation)
4. `A(fs) ≈ 40·log10(fc/fs)` dB for fs << fc
5. Exact: `A(fs) = 10·log10(((1−u)²+9u)/u²)` where `u = (fs/fc_stage)²`

---

## Design Procedure

**Step 1 — Target fc.**

**Step 2 — Verify two stages sufficient:** 40·log10(fc/fs) ≥ required attenuation.

**Step 3 — fc_stage = 0.3743 × fc.**

**Step 4 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 5 — C = 2.672 / (2π · fc · R).** Verify C ∈ [1 nF, 100 nF].

**Step 6 — Write netlist:**  
`EBUF VBUF 0 VIN 0 1`, then C1 from VBUF to n1, R1 from n1 to 0, C2 from n1 to VOUT, R2 from VOUT to 0.

---

## Worked Example 1

**Specification:** High-pass filter, fc = 1 kHz, high-Z electret microphone source, stopband ≥ 20 dB at 100 Hz.

**Step 1:** fc = 1 000 Hz.

**Step 2:** Asymptote: 40·log10(1000/100) = 40 dB ≥ 20 dB ✓.

**Step 3:** fc_stage = 0.3743 × 1 000 = 374.3 Hz.

**Step 4:** R = 10 kΩ.

**Step 5:** C = 2.672/(2π × 1000 × 10000) = 42.52 nF.

```spice
* 2-stage passive RC high-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  n1     42.52n
R1   n1    0      10k
C2   n1    VOUT   42.52n
R2   VOUT  0      10k
.end
```

---

## Worked Example 2

**Specification:** High-pass filter, fc = 5 kHz, high-Z source, stopband ≥ 20 dB at 500 Hz.

**Step 1:** fc = 5 000 Hz.

**Step 2:** 40·log10(10) = 40 dB ≥ 20 dB ✓.

**Step 3:** fc_stage = 0.3743 × 5 000 = 1 871.5 Hz.

**Step 4:** R = 10 kΩ.

**Step 5:** C = 2.672/(2π × 5 000 × 10 000) = 8.503 nF.

```spice
* 2-stage passive RC high-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  n1     8.503n
R1   n1    0      10k
C2   n1    VOUT   8.503n
R2   VOUT  0      10k
.end
```

---

## Worked Example 3

**Specification:** High-pass filter, fc = 20 kHz, high-impedance piezo transducer, stopband ≥ 20 dB at 2 kHz.

**Step 1:** fc = 20 000 Hz.

**Step 2:** 40·log10(10) = 40 dB ≥ 20 dB ✓.

**Step 3:** fc_stage = 0.3743 × 20 000 = 7 486 Hz.

**Step 4:** R = 2 kΩ.

**Step 5:** C = 2.672/(2π × 20 000 × 2 000) = 10.63 nF.

```spice
* 2-stage passive RC high-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  n1     10.63n
R1   n1    0      2k
C2   n1    VOUT   10.63n
R2   VOUT  0      2k
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Cutoff lower than expected | Using fc_stage = fc (single-stage formula) | Use C = 2.672/(2π·fc·R); fc_stage must be 0.374× fc |
| Source still loads filter | EBUF missing or C1 connects from VIN not VBUF | Add EBUF; C1 must start from VBUF |
| C > 100 nF | Low fc or large R | Reduce R (try 2–5 kΩ) |
| n1 floating | R1 or C2 not connected to n1 | Verify topology: C1→n1, R1 shunt from n1, C2→VOUT from n1 |
| Low-pass response | C and R swapped | C in series, R to ground |
| EBUF error | Wrong format | `EBUF VBUF 0 VIN 0 1` — six fields |
