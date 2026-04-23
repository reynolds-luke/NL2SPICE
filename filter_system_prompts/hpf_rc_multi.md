# High-Pass Filter, Two-Stage Passive RC (rc_multi)

This document explains how a two-stage cascaded passive RC high-pass filter works, including the inter-stage loading correction required when sizing components, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

Two CR high-pass stages are cascaded directly without a buffer. The second stage (R2 to ground) loads the first stage (C1–R1), so the combined response is not the product of two independent single-pole responses — the stages interact through the loading impedance.

**Use this topology when:**
- Steeper low-frequency rejection (≈ −40 dB/decade) is needed.
- Minimum component count (no op-amps) is priority.
- Source impedance is low.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

C1   VIN   n1     {C}
R1   n1    0      {R}
C2   n1    VOUT   {C}
R2   VOUT  0      {R}
.end
```

---

## Transfer Function (Two Identical Stages, R₁=R₂=R, C₁=C₂=C)

The loaded two-stage HPF transfer function:

$$H(s) = \frac{\tau^2 s^2}{1 + 3\tau s + \tau^2 s^2}, \quad \tau = RC$$

Same denominator as the loaded two-stage LPF — the denominator poles are at:

$$\omega_0 = 1/\tau, \quad Q = 1/3$$

**Combined −3 dB frequency** (where |H| drops to 1/√2 below the passband):

$$\omega_{3dB} = \frac{2.672}{\tau} = 2.672 \times \frac{1}{RC}$$

$$f_{3dB} = \frac{2.672}{2\pi RC} = 2.672 \times f_{c,\text{stage}}$$

→ To achieve a target high-pass cutoff fc, design each stage with:

$$f_{c,\text{stage}} = \frac{f_c}{2.672} = 0.3743 \times f_c$$

$$C = \frac{2.672}{2\pi \cdot f_c \cdot R} = \frac{1}{2\pi \cdot 0.3743 \cdot f_c \cdot R}$$

**Asymptotic roll-off** below fc: −40 dB/decade.

**Attenuation at stopband frequency fs (fs < fc):**

$$A(f_s) = 10 \log_{10}\!\left[\frac{(1 - u)^2 + 9u}{u^2}\right], \quad u = \left(\frac{f_s}{f_{c,\text{stage}}}\right)^2$$

For fs << fc: A(fs) ≈ 40·log10(fc/fs) dB.

---

## Key Equations

1. `fc_stage = 1 / (2π · R · C)`
2. `fc_combined = 2.672 · fc_stage`  (combined cutoff is higher than individual stage)
3. `fc_stage = fc_target / 2.672 = 0.3743 · fc_target`  (design each stage lower)
4. `C = 2.672 / (2π · fc · R)`  (design equation given target fc)
5. **Attenuation at fs:** `A(fs) ≈ 40·log10(fc/fs)` for fs << fc

---

## Design Procedure

**Step 1 — Target fc.**

**Step 2 — Verify two-stage roll-off is sufficient:**  
Asymptotically, A(fs) ≈ 40·log10(fc/fs). Confirm ≥ required spec.

**Step 3 — Compute each stage's corner frequency:**  
`fc_stage = 0.3743 × fc`

**Step 4 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 5 — Compute C = 2.672 / (2π · fc · R).**  
Check C ∈ [1 nF, 100 nF]. C will be larger than single-stage (stages designed at lower corner).

**Step 6 — Write the netlist:**  
Stage 1: C1 in series (VIN to n1), R1 shunt (n1 to 0).  
Stage 2: C2 in series (n1 to VOUT), R2 shunt (VOUT to 0).

---

## Worked Example 1

**Specification:** High-pass filter, fc = 1 kHz, stopband ≥ 40 dB at 100 Hz.

**Step 1:** fc = 1 000 Hz.

**Step 2:** Asymptote: 40·log10(1000/100) = 40 dB ✓ (at 1 decade below fc).  
Exact at 100 Hz: fc_stage = 374.3 Hz; u = (100/374.3)² = 0.07133.  
A = 10·log10(((1−0.0713)²+9×0.0713)/0.0713²) = 10·log10((0.858+0.642)/0.00509)  
= 10·log10(1.5/0.00509) = 10·log10(294.7) ≈ 24.7 dB.  
Exact value ~24.7 dB, not 40 dB. Two passive stages give ~25 dB at 10× below cutoff.  
For 40 dB spec, need fs much further from fc or use more stages.

**Step 3:** fc_stage = 0.3743 × 1000 = 374.3 Hz.

**Step 4:** R = 10 kΩ.

**Step 5:** C = 2.672/(2π × 1000 × 10000) = 42.52 nF.

```spice
* 2-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   n1     42.52n
R1   n1    0      10k
C2   n1    VOUT   42.52n
R2   VOUT  0      10k
.end
```

---

## Worked Example 2

**Specification:** High-pass filter, fc = 5 kHz, stopband ≥ 20 dB at 500 Hz.

**Step 1:** fc = 5 000 Hz.

**Step 2:** Asymptote: 40·log10(5000/500) = 40 dB ≥ 20 dB ✓.

**Step 3:** fc_stage = 0.3743 × 5 000 = 1 871.5 Hz.

**Step 4:** R = 10 kΩ.

**Step 5:** C = 2.672/(2π × 5000 × 10000) = 8.503 nF.

**Verify:** fc_stage = 1/(2π×10k×8.503n) = 1 872 Hz; fc_combined = 2.672×1872 = 5 001 Hz ✓.

```spice
* 2-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   n1     8.503n
R1   n1    0      10k
C2   n1    VOUT   8.503n
R2   VOUT  0      10k
.end
```

---

## Worked Example 3

**Specification:** High-pass filter, fc = 20 kHz, stopband ≥ 20 dB at 2 kHz.

**Step 1:** fc = 20 000 Hz.

**Step 2:** Asymptote: 40·log10(20000/2000) = 40 dB ≥ 20 dB ✓.

**Step 3:** fc_stage = 0.3743 × 20 000 = 7 486 Hz.

**Step 4:** R = 2 kΩ (need smaller R to keep C ≥ 1 nF at higher fc_stage).

**Step 5:** C = 2.672/(2π × 20000 × 2000) = 10.63 nF.  
Check: fc_stage = 1/(2π×2k×10.63n) = 7 497 Hz ≈ 7 486 Hz ✓.  
fc_combined = 2.672 × 7497 = 20 033 Hz ✓.

```spice
* 2-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   n1     10.63n
R1   n1    0      2k
C2   n1    VOUT   10.63n
R2   VOUT  0      2k
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Cutoff lower than expected | Using single-stage formula (fc = 1/2πRC) instead of two-stage correction | Each stage fc_stage = 0.3743 × fc_target; C = 2.672/(2π·fc·R) |
| Stopband insufficient | Near-cutoff approximation fails | Use exact formula or lower fc |
| Response looks low-pass | C and R positions swapped | C must be in series, R must shunt to ground |
| n1 node floating | C2 or R1 not connected to n1 | Verify: R1 (n1 to 0), C2 (n1 to VOUT) |
| C > 100 nF | fc_stage is very low (correct for low fc targets); R too large | Use smaller R (1–5 kΩ) or accept larger C |
| Source loads filter | Source impedance affects C1 | Use `buffered_rc_multi` |
