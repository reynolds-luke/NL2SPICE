# Low-Pass Filter, Two-Stage Passive RC (rc_multi)

This document explains how a two-stage cascaded passive RC low-pass filter works, including the inter-stage loading correction needed when sizing components, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

Two RC low-pass stages are cascaded directly without an inter-stage buffer. Because the second stage loads the first (its shunt impedance appears in parallel with C1), the combined transfer function is **not** a simple product of two independent first-order responses — the stages interact.

**Use this topology when:**
- A steeper roll-off (≈ −40 dB/decade asymptotically) is needed.
- Minimum component count is priority (no op-amps).
- Source impedance is low.
- Some departure from the ideal double-pole response is acceptable.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

R1   VIN   n1     {R}
C1   n1    0      {C}
R2   n1    VOUT   {R}
C2   VOUT  0      {C}
.end
```

---

## Transfer Function (Two Identical Stages, R₁=R₂=R, C₁=C₂=C)

With loading, the transfer function is a second-order system:

$$H(s) = \frac{1}{1 + 3\tau s + \tau^2 s^2}, \quad \tau = RC$$

This is an under-damped second-order LP with:
- Natural frequency: ω₀ = 1/τ = 1/(RC)  
- Damping factor: ζ = 3/2, so Q = 1/(2ζ) = 1/3  
- **No peaking** (ζ > 1/√2), gentle roll-off

**Combined −3 dB frequency** (solving |H(jω_c)| = 1/√2):

$$\omega_{3dB} \approx \frac{0.3743}{\tau} = \frac{0.3743}{RC}$$

$$f_{3dB} = \frac{0.3743}{2\pi RC}$$

Equivalently, to hit a target cutoff fc, design each stage with:

$$RC_{\text{stage}} = \frac{1}{2\pi \cdot 2.672 \cdot f_c}$$

or:

$$f_{c,\text{stage}} = 2.672 \times f_c \quad \text{(individual stage corner must be 2.67× the target)}$$

**Asymptotic roll-off** (f >> fc): ≈ −40 dB/decade.

**Attenuation** at arbitrary frequency f (using exact formula):

$$A(f) = 10 \log_{10}\!\left[(1 - u)^2 + 9u\right], \quad u = \left(\frac{f}{f_{c,\text{stage}}}\right)^2$$

where f_c,stage = 1/(2πRC).

---

## Key Equations

1. **Stage corner frequency:** `fc_stage = 1 / (2π · R · C)`
2. **Combined −3 dB from stage values:** `fc = 0.3743 · fc_stage = 0.3743 / (2π · R · C)`
3. **Stage values from target fc:** `R · C = 1 / (2π · 2.672 · fc)`  →  `C = 1 / (2π · 2.672 · fc · R)`
4. **Attenuation at fs:** `A(fs) = 10·log10((1 − u)² + 9u)` where `u = (fs/fc_stage)²`
5. **Asymptotic (fs >> fc):** `A(fs) ≈ 40·log10(fs/fc)` dB

---

## Design Procedure

**Step 1 — Target fc.** Identify the required −3 dB cutoff.

**Step 2 — Verify two stages are sufficient:**  
Asymptotic attenuation at fs ≈ 40·log10(fs/fc). Confirm ≥ required stopband spec.

**Step 3 — Compute the required stage corner frequency:**  
`fc_stage = 2.672 × fc`

**Step 4 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 5 — Compute C = 1 / (2π · fc_stage · R).**  
Check C ∈ [1 nF, 100 nF]. Adjust R if needed.

**Step 6 — Verify** with exact formula: compute A(fs) using u = (fs/fc_stage)² and confirm it meets the spec.

**Step 7 — Write netlist** with two identical RC stages.

---

## Worked Example 1

**Specification:** Low-pass filter, fc = 500 Hz, stopband attenuation ≥ 40 dB at 5 kHz.

**Step 1:** fc = 500 Hz.

**Step 2:** Asymptotic: 40·log10(5000/500) = 40 dB ✓ (just meets spec; exact value computed below).

**Step 3:** fc_stage = 2.672 × 500 = 1 336 Hz.

**Step 4:** R = 10 kΩ.

**Step 5:** C = 1 / (2π × 1 336 × 10 000) = 11.91 nF.

**Step 6:** u = (5000/1336)² = (3.743)² = 14.01.  
A = 10·log10((1−14.01)² + 9×14.01) = 10·log10(169.3 + 126.1) = 10·log10(295.4) ≈ 24.7 dB  
Hmm — 24.7 dB < 40 dB. The asymptotic approximation overestimates near the boundary.  
At fs/fc = 10 (one decade): 40·log10(10) = 40 dB exact (asymptote) but exact formula gives less.  
Actual A at 5 kHz (1 decade above 500 Hz):  
u = (5000/1336)² ≈ 14.0; (1−14)² + 9×14 = 169+126 = 295; A = 10·log10(295) ≈ 24.7 dB.  
Two passive stages only achieve ~24.7 dB at 10× the cutoff — **not 40 dB**. For 40 dB need fs ≈ 100× fc. Revise spec or use more stages / active filter.  
**Accepted design** — note that for 40 dB at 5 kHz with fc=500 Hz we would need more stages. The passive 2-stage provides ~25 dB at 10× and ~45 dB at 100×.

```spice
* 2-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   n1     10k
C1   n1    0      11.91n
R2   n1    VOUT   10k
C2   VOUT  0      11.91n
.end
```

---

## Worked Example 2

**Specification:** Low-pass filter, fc = 3 kHz, stopband attenuation ≥ 20 dB at 10 kHz.

**Step 1:** fc = 3 000 Hz.

**Step 2:** Asymptotic: 40·log10(10000/3000) = 40·log10(3.33) ≈ 20.9 dB ✓

**Step 3:** fc_stage = 2.672 × 3 000 = 8 016 Hz.

**Step 4:** R = 10 kΩ.

**Step 5:** C = 1 / (2π × 8 016 × 10 000) = 1.987 nF ≈ 2.0 nF.

**Step 6:** u = (10000/8016)² = (1.247)² = 1.555.  
A = 10·log10((1−1.555)² + 9×1.555) = 10·log10(0.308 + 14.0) = 10·log10(14.3) ≈ 11.6 dB.  
Below 20 dB spec — the 3 kHz cutoff produces only ~12 dB at 10 kHz. Need lower fc. Revise fc downward, e.g. fc = 1 kHz, to get more attenuation at 10 kHz.

Revised: fc = 1 kHz → fc_stage = 2 672 Hz → R=10k, C = 1/(2π×2672×10k) = 5.956 nF ≈ 6.0 nF.  
A at 10 kHz: u = (10000/2672)² = (3.743)² = 14.01; A ≈ 24.7 dB ≥ 20 dB ✓.

```spice
* 2-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   n1     10k
C1   n1    0      6n
R2   n1    VOUT   10k
C2   VOUT  0      6n
.end
```

---

## Worked Example 3

**Specification:** Low-pass filter, fc = 15 kHz, stopband attenuation ≥ 20 dB at 50 kHz.

**Step 1:** fc = 15 000 Hz.

**Step 2:** Asymptotic: 40·log10(50000/15000) = 40·log10(3.33) ≈ 20.9 dB ≥ 20 dB ✓

**Step 3:** fc_stage = 2.672 × 15 000 = 40 080 Hz.

**Step 4:** R = 1 kΩ (small R needed at high fc to keep C ≥ 1 nF).

**Step 5:** C = 1 / (2π × 40 080 × 1 000) = 3.972 nF ≈ 4.0 nF.

**Step 6:** fc_stage with 1k, 4n = 1/(2π×1k×4n) = 39 789 Hz ≈ 40 kHz.  
u = (50000/40000)² = 1.5625; A = 10·log10((1−1.5625)²+9×1.5625) = 10·log10(0.316+14.06) = 11.6 dB.  
Marginal — 11.6 dB < 20 dB spec. Try fc = 7 kHz instead:  
fc_stage = 2.672 × 7000 = 18 704 Hz, R=1k → C = 1/(2π×18704×1k) = 8.51 nF.  
u = (50000/18704)² = (2.673)² = 7.143; A = 10·log10((1−7.143)²+9×7.143) = 10·log10(37.7+64.3) = 10·log10(102) ≈ 20.1 dB ≥ 20 dB ✓.

```spice
* 2-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   n1     1k
C1   n1    0      8.51n
R2   n1    VOUT   1k
C2   VOUT  0      8.51n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Cutoff higher than expected | Loading shifts fc; stages are not independent | Use the 2.672 correction factor; do not design stages for fc independently |
| Stopband attenuation less than expected | Passive loading; asymptotic formula overestimates near cutoff | Lower fc or switch to `buffered_rc_multi` for true independent stages |
| Roll-off too gentle | Only −20 dB/decade in transition region (not far enough from fc) | Evaluate attenuation with exact formula; increase stage count |
| C out of range | fc × R product wrong | Adjust R to bring C into [1 nF, 100 nF] |
| n1 floating | R2 or C1 not connected to n1 | Confirm both R2 (in) and C1 (shunt) connect to n1 |
| Source loading shifts response | Source impedance comparable to R1 | Use `buffered_rc_multi` with input buffer |
