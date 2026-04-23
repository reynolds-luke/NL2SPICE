# High-Pass Filter, Single-Stage RC (rc_single)

This document explains how a single-stage passive RC high-pass filter works, how to size its components for a given cutoff frequency, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

A single-stage RC high-pass filter passes high frequencies and attenuates low frequencies. One capacitor is placed in series with the signal path and one resistor shunts to ground. It is a first-order filter with a +20 dB/decade rise below the cutoff frequency.

**Use this topology when:**
- DC blocking or low-frequency noise rejection is needed.
- A gentle +20 dB/decade roll-off is sufficient.
- Source impedance is low.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

C1   VIN   VOUT   {C}
R1   VOUT  0      {R}
.end
```

---

## Transfer Function

$$H(j\omega) = \frac{j(f/f_c)}{1 + j(f/f_c)}$$

where the **cutoff frequency** is:

$$f_c = \frac{1}{2\pi R C}$$

**Magnitude response:**

$$|H(f)| = \frac{f/f_c}{\sqrt{1 + (f/f_c)^2}}$$

At f >> fc: |H| → 1 (passband, 0 dB).  
At f = fc: |H| = 1/√2 (−3 dB).  
At f << fc: |H| ≈ f/fc (−20 dB/decade roll-off below fc).

**Attenuation below the passband** (positive = loss):

$$A(f) = 10\log_{10}\!\left(1 + \left(\frac{f_c}{f}\right)^2\right) \text{ dB}$$

**Asymptotic stopband attenuation** (f << fc):

$$A(f) \approx 20 \log_{10}\!\left(\frac{f_c}{f}\right) \text{ dB}$$

---

## Key Equations

1. `fc = 1 / (2π · R · C)`
2. `C = 1 / (2π · fc · R)`
3. `R = 1 / (2π · fc · C)`
4. **Attenuation at any frequency f:** `A(f) = 10·log10(1 + (fc/f)²)` dB
5. **Frequency for required stopband attenuation A:** `f = fc / √(10^(A/10) − 1)`
6. **Phase shift:** `φ(f) = +arctan(fc/f)`  (+45° at f = fc)

---

## Design Procedure

**Step 1 — Identify fc.**  
The cutoff frequency is where gain drops −3 dB below the passband (high-frequency flat region).

**Step 2 — Verify single-stage roll-off meets stopband spec.**  
At stopband frequency fs (fs < fc): A = 10·log10(1 + (fc/fs)²). If insufficient, use multi-stage.

**Step 3 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 4 — Compute C = 1 / (2π · fc · R).**  
Check C ∈ [1 nF, 100 nF].

**Step 5 — Verify fc** with chosen values.

---

## Worked Example 1

**Specification:** High-pass filter, fc = 500 Hz, stopband attenuation ≥ 20 dB at 50 Hz.

**Step 1:** fc = 500 Hz.

**Step 2:** A at 50 Hz = 10·log10(1+(500/50)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 10 kΩ.

**Step 4:** C = 1/(2π × 500 × 10 000) = 31.83 nF.

**Step 5:** fc = 1/(2π × 10k × 31.83n) = 500.1 Hz ✓

```spice
* Single-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   VOUT   31.83n
R1   VOUT  0      10k
.end
```

---

## Worked Example 2

**Specification:** High-pass filter, fc = 5 kHz, DC blocking, stopband ≥ 20 dB at 500 Hz.

**Step 1:** fc = 5 000 Hz.

**Step 2:** A at 500 Hz = 10·log10(1+(5000/500)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 10 kΩ.

**Step 4:** C = 1/(2π × 5 000 × 10 000) = 3.183 nF.

**Step 5:** fc = 1/(2π × 10k × 3.183n) = 5 001 Hz ✓

```spice
* Single-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   VOUT   3.183n
R1   VOUT  0      10k
.end
```

---

## Worked Example 3

**Specification:** High-pass filter, fc = 20 kHz, rejects low-frequency vibration, stopband ≥ 20 dB at 2 kHz.

**Step 1:** fc = 20 000 Hz.

**Step 2:** A at 2 kHz = 10·log10(1+(20000/2000)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 4 kΩ (small R needed because C must stay ≥ 1 nF at high fc).

**Step 4:** C = 1/(2π × 20 000 × 4 000) = 1.989 nF ≈ 2.0 nF.

**Step 5:** fc = 1/(2π × 4k × 2.0n) = 19.89 kHz ≈ 20 kHz ✓

```spice
* Single-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   VOUT   2n
R1   VOUT  0      4k
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Response is low-pass, not high-pass | R and C positions swapped | C must be in series (VIN to VOUT), R must shunt to ground |
| Cutoff frequency wrong | Incorrect R or C | Recalculate fc = 1/(2πRC) |
| Stopband attenuation insufficient | Single stage only −20 dB/decade | Switch to `rc_multi` (two stages, −40 dB/decade) |
| C < 1 nF | R too small, fc too high | Decrease R toward 1 kΩ, or accept larger C |
| C > 100 nF | R too large | Decrease R; 10 kΩ is a good starting point |
| Source loading shifts cutoff | Source impedance adds to apparent R | Use `buffered_rc_single` to isolate the source |
| VOUT has DC offset error | Capacitor leakage or wrong topology | Check C is truly in series (VIN to internal node), R to ground |
