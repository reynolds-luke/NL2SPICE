# High-Pass Filter, Buffered Single-Stage RC (buffered_rc_single)

This document explains how a buffered single-stage passive RC high-pass filter works, how to size its components, and how to write its SPICE netlist. The input buffer (VCVS) prevents source loading from shifting the cutoff frequency. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An ideal unity-gain input buffer (VCVS) is placed before the single-stage CR high-pass network. The buffer presents zero source impedance to the CR network, so the cutoff frequency is set only by R and C, not by the driving source impedance.

**Use this topology when:**
- The source impedance is high or unknown.
- Precise, source-independent cutoff frequency is needed.
- Single-stage −20 dB/decade roll-off is sufficient.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  VOUT   {C}
R1   VOUT  0      {R}
.end
```

---

## Transfer Function

From VBUF to VOUT (identical to unbuffered HPF):

$$H(j\omega) = \frac{j(f/f_c)}{1 + j(f/f_c)}, \quad f_c = \frac{1}{2\pi R C}$$

**Attenuation below passband:**

$$A(f) = 10\log_{10}\!\left(1 + \left(\frac{f_c}{f}\right)^2\right) \text{ dB}$$

**Asymptotic:** A(f) ≈ 20·log10(fc/f) for f << fc.

---

## Key Equations

1. `fc = 1 / (2π · R · C)`
2. `C = 1 / (2π · fc · R)`
3. `A(f) = 10·log10(1 + (fc/f)²)` dB
4. Stopband frequency for target attenuation A: `fs = fc / √(10^(A/10) − 1)`

---

## Design Procedure

**Step 1 — Target fc.**

**Step 2 — Verify roll-off:** A(fs) = 10·log10(1+(fc/fs)²). If < spec, use `buffered_rc_multi`.

**Step 3 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 4 — Compute C = 1 / (2π · fc · R).** Check C ∈ [1 nF, 100 nF].

**Step 5 — Write netlist:**  
`EBUF VBUF 0 VIN 0 1`, then C1 from VBUF to VOUT, R1 from VOUT to 0.

---

## Worked Example 1

**Specification:** High-pass filter, fc = 1 kHz, high-impedance microphone source, stopband ≥ 20 dB at 100 Hz.

**Step 1:** fc = 1 000 Hz.

**Step 2:** A at 100 Hz = 10·log10(1+(1000/100)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 15 kΩ.

**Step 4:** C = 1/(2π × 1 000 × 15 000) = 10.61 nF.

**Step 5:** fc = 1/(2π × 15k × 10.61n) = 1 001 Hz ✓

```spice
* Single-stage passive RC high-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  VOUT   10.61n
R1   VOUT  0      15k
.end
```

---

## Worked Example 2

**Specification:** High-pass filter, fc = 8 kHz, rejects sub-8 kHz components, high-Z source, stopband ≥ 20 dB at 800 Hz.

**Step 1:** fc = 8 000 Hz.

**Step 2:** A at 800 Hz = 10·log10(1+(8000/800)²) ≈ 20.04 dB ✓

**Step 3:** R = 10 kΩ.

**Step 4:** C = 1/(2π × 8 000 × 10 000) = 1.989 nF ≈ 2.0 nF.

**Step 5:** fc = 1/(2π × 10k × 2.0n) = 7 958 Hz ≈ 8 kHz ✓

```spice
* Single-stage passive RC high-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  VOUT   2n
R1   VOUT  0      10k
.end
```

---

## Worked Example 3

**Specification:** High-pass filter, fc = 30 kHz, ultrasonic signal path, high-impedance transducer, stopband ≥ 20 dB at 3 kHz.

**Step 1:** fc = 30 000 Hz.

**Step 2:** A at 3 kHz = 10·log10(1+(30000/3000)²) ≈ 20.04 dB ✓

**Step 3:** R = 2.5 kΩ.

**Step 4:** C = 1/(2π × 30 000 × 2 500) = 2.122 nF.

**Step 5:** fc = 1/(2π × 2.5k × 2.122n) = 30 005 Hz ✓

```spice
* Single-stage passive RC high-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  VOUT   2.122n
R1   VOUT  0      2.5k
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Response low-pass, not high-pass | C1 and R1 positions swapped | C1 in series (VBUF → VOUT), R1 shunt (VOUT → 0) |
| Cutoff shifts with source impedance | EBUF not connected before C1 | Ensure C1 connects from VBUF (buffer output), not VIN |
| EBUF syntax error | Wrong node order | Must be `EBUF VBUF 0 VIN 0 1` |
| Stopband insufficient | Single stage only −20 dB/decade | Use `buffered_rc_multi` |
| C < 1 nF | fc × R too large | Use smaller R (e.g., 1–5 kΩ) |
| C > 100 nF | fc too low or R too large | Reduce R |
