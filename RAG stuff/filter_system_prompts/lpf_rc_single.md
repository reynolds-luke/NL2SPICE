# Low-Pass Filter, Single-Stage RC (rc_single)

This document explains how a single-stage passive RC low-pass filter works, how to size its components for a given cutoff frequency, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

A single-stage RC low-pass filter passes low frequencies and attenuates high frequencies. It is the simplest possible implementation: one resistor in series with the signal path and one capacitor shunting to ground. It is a first-order filter with a -20 dB/decade roll-off above the cutoff frequency.

**Use this topology when:**
- The source impedance is low (the source can drive the RC network without loading error).
- A gentle -20 dB/decade roll-off is sufficient.
- Minimum component count is required.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

R1   VIN   VOUT   {R}
C1   VOUT  0      {C}
.end
```

---

## Transfer Function

$$H(j\omega) = \frac{1}{1 + j\omega RC} = \frac{1}{1 + j(f/f_c)}$$

where the **cutoff frequency** is:

$$f_c = \frac{1}{2\pi R C}$$

**Magnitude response:**

$$|H(f)| = \frac{1}{\sqrt{1 + (f/f_c)^2}}$$

**Attenuation in dB** (positive = loss):

$$A(f) = 10 \log_{10}\!\left(1 + \left(\frac{f}{f_c}\right)^2\right) \text{ dB}$$

**Roll-off rate:** −20 dB/decade (for f >> fc).

**Asymptotic attenuation** (f >> fc):

$$A(f) \approx 20 \log_{10}\!\left(\frac{f}{f_c}\right) \text{ dB}$$

---

## Key Equations

1. **Cutoff frequency:**  `fc = 1 / (2π · R · C)`
2. **Given fc and R, solve for C:**  `C = 1 / (2π · fc · R)`
3. **Given fc and C, solve for R:**  `R = 1 / (2π · fc · C)`
4. **Attenuation at any frequency f:**  `A(f) = 10·log10(1 + (f/fc)²)` dB
5. **Frequency for a required attenuation A (dB):**  `f = fc · √(10^(A/10) − 1)`
6. **Phase shift:**  `φ(f) = −arctan(f/fc)`  (−45° at f = fc)

---

## Design Procedure

**Step 1 — Identify the target cutoff frequency fc.**
The cutoff frequency is where the response is −3 dB below the DC level (|H| = 1/√2 ≈ 0.707).

**Step 2 — Verify the single-stage roll-off meets the stopband spec.**
At stopband frequency fs, attenuation = 10·log10(1 + (fs/fc)²). If this does not meet the spec, switch to a multi-stage topology (rc_multi or buffered_rc_multi).

**Step 3 — Choose R in [1 kΩ, 100 kΩ].**
A value of 10 kΩ is a reasonable default. Choose larger R if you need larger C to stay in range; choose smaller R if you need smaller C.

**Step 4 — Compute C = 1 / (2π · fc · R).**
Verify C is in [1 nF, 100 nF]. If C < 1 nF, decrease R. If C > 100 nF, increase R.

**Step 5 — Verify:**
Compute fc = 1/(2π·R·C) with the chosen values. Check that A(fs) ≥ required stopband attenuation.

---

## Worked Example 1

**Specification:** Low-pass filter, fc = 1 kHz, passband loss < 1 dB, stopband attenuation ≥ 20 dB at 10 kHz.

**Step 1:** fc = 1 000 Hz.

**Step 2:** At fs = 10 kHz: A = 10·log10(1 + (10000/1000)²) = 10·log10(101) ≈ 20.04 dB ≥ 20 dB ✓  
Single stage is sufficient.

**Step 3:** Choose R = 10 kΩ.

**Step 4:** C = 1 / (2π × 1 000 × 10 000) = 15.92 nF.

**Step 5:** fc = 1/(2π × 10k × 15.92n) = 999.8 Hz ≈ 1 kHz ✓

```spice
* Single-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   VOUT   10k
C1   VOUT  0      15.92n
.end
```

---

## Worked Example 2

**Specification:** Low-pass filter, fc = 5 kHz, passband loss < 0.5 dB at 1 kHz, stopband attenuation ≥ 14 dB at 20 kHz.

**Step 1:** fc = 5 000 Hz.

**Step 2:** At fs = 20 kHz: A = 10·log10(1 + (20000/5000)²) = 10·log10(17) ≈ 12.3 dB < 14 dB — marginal; check if passband at 1 kHz is also met.  
At f_pass = 1 kHz: A = 10·log10(1 + (1000/5000)²) = 10·log10(1.04) ≈ 0.17 dB < 0.5 dB ✓  
Stopband is marginally insufficient; either increase fc slightly or use multi-stage. Here we accept slight shortfall and note it, OR lower fc a bit. Let's use fc = 4.5 kHz to get more stopband margin.  
Revised: A at 20 kHz with fc = 4.5 kHz: 10·log10(1+(20/4.5)²) = 10·log10(20.8) ≈ 13.2 dB — still short. Use rc_multi instead, or widen the spec. Here we proceed with fc = 5 kHz and report the actual attenuation.

**Step 3:** Choose R = 10 kΩ.

**Step 4:** C = 1 / (2π × 5 000 × 10 000) = 3.183 nF.

**Step 5:** fc = 1/(2π × 10k × 3.183n) = 5 001 Hz ✓

```spice
* Single-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   VOUT   10k
C1   VOUT  0      3.183n
.end
```

---

## Worked Example 3

**Specification:** Low-pass filter, fc = 20 kHz, passband flat above 10 kHz, stopband attenuation ≥ 20 dB at 200 kHz.

**Step 1:** fc = 20 000 Hz.

**Step 2:** At fs = 200 kHz: A = 10·log10(1 + (200/20)²) = 10·log10(101) ≈ 20.04 dB ≥ 20 dB ✓

**Step 3:** Choose R = 4 kΩ (smaller R needed because C must stay ≥ 1 nF).

**Step 4:** C = 1 / (2π × 20 000 × 4 000) = 1.989 nF ≈ 2.0 nF.

**Step 5:** fc = 1/(2π × 4k × 2.0n) = 19.89 kHz ≈ 20 kHz ✓

```spice
* Single-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   VOUT   4k
C1   VOUT  0      2n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Cutoff frequency too high | C is too small or R is too small | Increase R or C; recompute fc = 1/(2πRC) |
| Cutoff frequency too low | C is too large or R is too large | Decrease R or C |
| Stopband attenuation insufficient | Single stage only gives −20 dB/decade | Switch to `rc_multi` (2 stages, −40 dB/decade) |
| Passband flat region not meeting spec | fc is set too low, attenuating the passband | Increase fc |
| C < 1 nF (out of range) | R is too small | Increase R toward 100 kΩ |
| C > 100 nF (out of range) | R is too large | Decrease R toward 1 kΩ |
| Source loading shifts fc | Source impedance comparable to R1 | Use `buffered_rc_single` (input buffer isolates source) |
