# Low-Pass Filter, Two-Stage Buffered RC (buffered_rc_multi)

This document explains how a two-stage passive RC low-pass filter with an input buffer works, how to size components (including the loading correction), and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An ideal unity-gain input buffer (VCVS) drives two cascaded RC low-pass stages. Because the buffer presents zero output impedance, and because no inter-stage buffer isolates stage 1 from stage 2, the second stage still loads the first — **however**, the source is fully isolated by the input buffer.

For the LPF in this project the two RC stages share identical R and C values without a mid-stage buffer, so the combined response follows the loaded two-stage formula (same as rc_multi). The input buffer ensures the source does not affect fc.

**Use this topology when:**
- The signal source has high or variable impedance.
- Steeper −40 dB/decade roll-off is required.
- You want the cutoff to be independent of source impedance.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  n1     {R}
C1   n1    0      {C}
R2   n1    VOUT   {R}
C2   VOUT  0      {C}
.end
```

---

## Transfer Function

Same denominator as the passive two-stage (rc_multi):

$$H(s) = \frac{1}{1 + 3\tau s + \tau^2 s^2}, \quad \tau = RC$$

**Combined −3 dB frequency** (loaded two-stage formula):

$$f_{3dB} = \frac{0.3743}{2\pi RC}$$

→ Design each stage for:

$$f_{c,\text{stage}} = 2.672 \times f_c$$

$$C = \frac{1}{2\pi \cdot 2.672 \cdot f_c \cdot R}$$

**Asymptotic roll-off:** −40 dB/decade.

> **Note:** If you need truly independent stages (buffered_rc_multi with a mid-stage buffer), the correction factor changes to 1.5538 (buffered stages formula). The current project's buffered_rc_multi topology uses only an input buffer without a mid-stage buffer, so the 2.672 factor applies.

---

## Key Equations

1. `fc_stage = 1 / (2π · R · C)`
2. `fc_combined = 0.3743 · fc_stage`
3. `C = 1 / (2π · 2.672 · fc · R)`  (design equation)
4. `A(f) = 10·log10((1−u)² + 9u)` where `u = (f/fc_stage)²`
5. **Asymptotic:** `A(f) ≈ 40·log10(f/fc)` for `f >> fc`

---

## Design Procedure

**Step 1 — Target fc.**

**Step 2 — Confirm two-stage roll-off suffices:**  
Asymptotically, attenuation at fs ≈ 40·log10(fs/fc). Use exact formula for confirmation.

**Step 3 — Compute fc_stage = 2.672 × fc.**

**Step 4 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 5 — Compute C = 1 / (2π · fc_stage · R).**  
Verify C ∈ [1 nF, 100 nF].

**Step 6 — Write netlist:**  
First element: `EBUF VBUF 0 VIN 0 1`.  
Stage 1: R1 from VBUF to n1, C1 from n1 to 0.  
Stage 2: R2 from n1 to VOUT, C2 from VOUT to 0.

---

## Worked Example 1

**Specification:** Low-pass filter, fc = 1 kHz, high-impedance source, stopband ≥ 20 dB at 5 kHz.

**Step 1:** fc = 1 000 Hz.

**Step 2:** 40·log10(5000/1000) = 40·log10(5) ≈ 28 dB ≥ 20 dB ✓ (asymptote).  
Exact: fc_stage = 2 672 Hz; u = (5000/2672)² = (1.872)² = 3.504.  
A = 10·log10((1−3.504)²+9×3.504) = 10·log10(6.27+31.54) = 10·log10(37.8) ≈ 15.8 dB.  
Below 20 dB. Revise fc = 500 Hz for better margin.  
fc_stage = 2.672 × 500 = 1 336 Hz; u = (5000/1336)² = 14.01; A ≈ 24.7 dB ✓.  
Use fc = 500 Hz, R = 10k, C = 1/(2π×1336×10k) = 11.91 nF.

```spice
* 2-stage passive RC low-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  n1     10k
C1   n1    0      11.91n
R2   n1    VOUT   10k
C2   VOUT  0      11.91n
.end
```

---

## Worked Example 2

**Specification:** Low-pass filter, fc = 5 kHz, sensor output (50 kΩ source), stopband ≥ 20 dB at 20 kHz.

**Step 1:** fc = 5 000 Hz.

**Step 2:** Asymptote: 40·log10(20/5) = 40·log10(4) ≈ 24 dB ✓.  
Exact check: fc_stage = 2.672×5000 = 13 360 Hz; u = (20000/13360)² = (1.497)² = 2.241.  
A = 10·log10((1−2.241)²+9×2.241) = 10·log10(1.54+20.17) = 10·log10(21.7) ≈ 13.4 dB — below spec.  
Use fc = 2 kHz instead: fc_stage = 5 344 Hz, u at 20 kHz = (20000/5344)² = 14.0; A ≈ 24.7 dB ✓.  
R = 10k, C = 1/(2π×5344×10k) = 2.978 nF ≈ 3.0 nF.

```spice
* 2-stage passive RC low-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  n1     10k
C1   n1    0      3n
R2   n1    VOUT   10k
C2   VOUT  0      3n
.end
```

---

## Worked Example 3

**Specification:** Low-pass filter, fc = 20 kHz, high-impedance DAC output, stopband ≥ 20 dB at 100 kHz.

**Step 1:** fc = 20 000 Hz.

**Step 2:** 40·log10(100/20) = 40·log10(5) ≈ 28 dB ✓.  
Exact: fc_stage = 53 440 Hz; u = (100000/53440)² = (1.872)² = 3.504.  
A = 10·log10(6.27+31.54) ≈ 15.8 dB — below 20 dB. Lower fc.  
Use fc = 10 kHz: fc_stage = 26 720 Hz; u = (100000/26720)² = (3.743)² = 14.01; A ≈ 24.7 dB ✓.  
R = 1 kΩ, C = 1/(2π×26720×1000) = 5.957 nF ≈ 6.0 nF.

```spice
* 2-stage passive RC low-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  n1     1k
C1   n1    0      6n
R2   n1    VOUT   1k
C2   VOUT  0      6n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Cutoff wrong despite buffer | Correction factor not applied | Use C = 1/(2π × 2.672 × fc × R), not C = 1/(2π × fc × R) |
| Stopband attenuation less than asymptote | Exact formula needed near cutoff | Evaluate with u = (fs/fc_stage)², lower fc for more margin |
| EBUF wired incorrectly | Wrong node order | Must be `EBUF VBUF 0 VIN 0 1` — output=VBUF, input=VIN |
| Stage 1 output node mismatch | n1 not connected consistently | R1 out → n1, C1 shunt → n1, R2 in → n1 |
| C out of range | fc too high or R too large/small | Adjust R; for fc > 10 kHz use R ≤ 5 kΩ |
| Source still loading | EBUF missing | Ensure EBUF is present and R1 connects from VBUF not VIN |
