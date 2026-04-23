# Low-Pass Filter, Buffered Single-Stage RC (buffered_rc_single)

This document explains how a buffered single-stage passive RC low-pass filter works, how to size its components, and how to write its SPICE netlist. The topology adds an ideal input buffer (VCVS) to isolate the source from the RC network. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

This topology adds an ideal unity-gain input buffer (VCVS voltage follower) before the single-stage RC low-pass network. The buffer presents zero output impedance to the RC network, so the cutoff frequency is determined solely by R and C — not by the driving source impedance.

**Use this topology when:**
- The signal source has high or unknown output impedance.
- Cutoff frequency accuracy is critical and must not depend on source impedance.
- A single-stage −20 dB/decade roll-off is sufficient.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  VOUT   {R}
C1   VOUT  0      {C}
.end
```

---

## Transfer Function

From VBUF to VOUT (same as unbuffered single-stage LPF):

$$H(j\omega) = \frac{1}{1 + j(f/f_c)}$$

$$f_c = \frac{1}{2\pi R C}$$

**Magnitude:**

$$|H(f)| = \frac{1}{\sqrt{1 + (f/f_c)^2}}$$

**Attenuation in dB:**

$$A(f) = 10\log_{10}\!\left(1 + \left(\frac{f}{f_c}\right)^2\right) \text{ dB}$$

**Roll-off:** −20 dB/decade.

---

## Key Equations

1. `fc = 1 / (2π · R · C)`
2. `C = 1 / (2π · fc · R)`
3. `R = 1 / (2π · fc · C)`
4. `A(f) = 10·log10(1 + (f/fc)²)` dB
5. `f for attenuation A: f = fc · √(10^(A/10) − 1)`

The buffer introduces no poles or zeros; only R and C determine fc.

---

## Design Procedure

**Step 1 — Identify target fc.**

**Step 2 — Verify single-stage roll-off is sufficient:**  
A(fs) = 10·log10(1 + (fs/fc)²). If insufficient, use `buffered_rc_multi`.

**Step 3 — Choose R ∈ [1 kΩ, 100 kΩ].**  
10 kΩ is a good default.

**Step 4 — Compute C = 1 / (2π · fc · R).**  
Check C ∈ [1 nF, 100 nF].

**Step 5 — Write the netlist:**  
- Add `EBUF VBUF 0 VIN 0 1` as the first active element.
- Connect R1 from VBUF to VOUT.
- Connect C1 from VOUT to 0.

---

## Worked Example 1

**Specification:** Low-pass filter, fc = 2 kHz, source impedance unknown (up to 50 kΩ), passband loss < 1 dB, stopband attenuation ≥ 20 dB at 20 kHz.

**Step 1:** fc = 2 000 Hz.

**Step 2:** A at 20 kHz = 10·log10(1 + (20000/2000)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 15 kΩ.

**Step 4:** C = 1 / (2π × 2 000 × 15 000) = 5.305 nF.

**Step 5:** fc = 1/(2π × 15k × 5.305n) = 2 001 Hz ✓

```spice
* Single-stage passive RC low-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  VOUT   15k
C1   VOUT  0      5.305n
.end
```

---

## Worked Example 2

**Specification:** Low-pass filter, fc = 8 kHz, high-impedance sensor source, stopband attenuation ≥ 20 dB at 80 kHz.

**Step 1:** fc = 8 000 Hz.

**Step 2:** A at 80 kHz = 10·log10(1 + (80/8)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 10 kΩ.

**Step 4:** C = 1 / (2π × 8 000 × 10 000) = 1.989 nF ≈ 2.0 nF.

**Step 5:** fc = 1/(2π × 10k × 2.0n) = 7 958 Hz ≈ 8 kHz ✓

```spice
* Single-stage passive RC low-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  VOUT   10k
C1   VOUT  0      2n
.end
```

---

## Worked Example 3

**Specification:** Low-pass filter, fc = 30 kHz, high-impedance piezo source, stopband attenuation ≥ 20 dB at 300 kHz.

**Step 1:** fc = 30 000 Hz.

**Step 2:** A at 300 kHz = 10·log10(1 + (300/30)²) = 10·log10(101) ≈ 20.04 dB ✓

**Step 3:** R = 2.5 kΩ (small R needed because C must stay ≥ 1 nF at high fc).

**Step 4:** C = 1 / (2π × 30 000 × 2 500) = 2.122 nF.

**Step 5:** fc = 1/(2π × 2.5k × 2.122n) = 30 005 Hz ✓

```spice
* Single-stage passive RC low-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  VOUT   2.5k
C1   VOUT  0      2.122n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Cutoff shifts with different sources | Buffer missing or EBUF wired incorrectly | Verify `EBUF VBUF 0 VIN 0 1`; R1 connects from VBUF, not VIN |
| EBUF syntax error | Wrong number of nodes | Format: `EBUF out 0 in 0 gain` — six fields required |
| Cutoff frequency wrong | R or C value incorrect | Recalculate: `fc = 1/(2πRC)` |
| Stopband attenuation insufficient | Single stage only −20 dB/decade | Switch to `buffered_rc_multi` |
| C out of range | fc × R product too large or too small | Adjust R to bring C into [1 nF, 100 nF] |
| VBUF floating | EBUF element missing from netlist | Add `EBUF VBUF 0 VIN 0 1` before R1 |
