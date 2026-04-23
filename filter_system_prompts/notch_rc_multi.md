# Notch Filter, Two-Stage Passive Twin-T RC (rc_multi)

This document explains how a two-stage cascaded passive RC Twin-T notch filter works, how cascading deepens the notch, and how to write its SPICE netlist. Note that inter-stage loading causes some passband attenuation; use the buffered variant to avoid this. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

Two identical Twin-T notch sections are cascaded in series. Both stages are tuned to the same notch frequency f₀. Cascading multiplies the transfer functions, producing a deeper notch and steeper skirts than a single stage.

**Use this topology when:**
- Higher notch depth (greater attenuation at f₀) is required.
- Steeper transition from passband to notch is needed.
- No op-amps are available.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

RTA11  VIN      NTA1A    {R}
RTA12  NTA1A    NTA1OUT  {R}
CTA1S1 NTA1A    0        {C}
CTA1S2 NTA1A    0        {C}

CTB11  VIN      NTB1A    {C}
CTB12  NTB1A    NTA1OUT  {C}
RTB1S1 NTB1A    0        {R}
RTB1S2 NTB1A    0        {R}

RTA21  NTA1OUT  NTA2A    {R}
RTA22  NTA2A    NTA2OUT  {R}
CTA2S1 NTA2A    0        {C}
CTA2S2 NTA2A    0        {C}

CTB21  NTA1OUT  NTB2A    {C}
CTB22  NTB2A    NTA2OUT  {C}
RTB2S1 NTB2A    0        {R}
RTB2S2 NTB2A    0        {R}

EOUT VOUT  0     NTA2OUT  0  1
.end
```

---

## Transfer Function

Each stage has the single-stage Twin-T transfer function:

$$H_1(s) = H_2(s) = \frac{1 + \tau^2 s^2}{1 + 4\tau s + \tau^2 s^2}, \quad \tau = RC$$

Combined:

$$H(s) = H_1(s) \times H_2(s) = \left(\frac{1 + \tau^2 s^2}{1 + 4\tau s + \tau^2 s^2}\right)^2$$

**Notch frequency** (same for both stages):

$$f_0 = \frac{1}{2\pi R C}$$

At f₀: H = 0 for each stage → combined H = 0 (theoretically deeper notch).

**Attenuation near f₀** (cascaded):  
The combined notch is deeper but the −3 dB bandwidth is slightly narrower than a single stage.

For cascaded identical notch filters, if each stage has −A dB at frequency f, the combined response gives −2A dB at the same frequency. The combined −3 dB frequencies shift inward slightly (the −3 dB point of the combination is where each stage produces −1.5 dB).

**Approximate −3 dB passband edges for two identical stages:**  
Solve |H_single|² = 1/√2 → each stage must be at −1.5 dB at the combined −3 dB frequency.  
In practice, the edges move inward by a factor of ~0.85–0.95, making the notch slightly narrower.

---

## Key Equations

1. `f0 = 1 / (2π · R · C)` — same for both stages
2. `C = 1 / (2π · f0 · R)`
3. **Single-stage −3 dB edges:** `f_L ≈ 0.2361 × f0`, `f_H ≈ 4.2361 × f0`
4. **Two-stage combined:** edges move slightly inward; use single-stage equations as approximation
5. **Notch depth:** ≈ 2× the single-stage dB depth (in dB scale, add the two attenuations)
6. Both stages must use identical R and C values

---

## SPICE Component Naming (Two Stages)

| Function | Stage 1 | Stage 2 |
|----------|---------|---------|
| Resistive series (arm A, element 1) | `RTA11 VIN NTA1A R` | `RTA21 NTA1OUT NTA2A R` |
| Resistive series (arm A, element 2) | `RTA12 NTA1A NTA1OUT R` | `RTA22 NTA2A NTA2OUT R` |
| Cap shunt at nta (2C, element 1) | `CTA1S1 NTA1A 0 C` | `CTA2S1 NTA2A 0 C` |
| Cap shunt at nta (2C, element 2) | `CTA1S2 NTA1A 0 C` | `CTA2S2 NTA2A 0 C` |
| Cap series (arm B, element 1) | `CTB11 VIN NTB1A C` | `CTB21 NTA1OUT NTB2A C` |
| Cap series (arm B, element 2) | `CTB12 NTB1A NTA1OUT C` | `CTB22 NTB2A NTA2OUT C` |
| Res shunt at ntb (R/2, element 1) | `RTB1S1 NTB1A 0 R` | `RTB2S1 NTB2A 0 R` |
| Res shunt at ntb (R/2, element 2) | `RTB1S2 NTB1A 0 R` | `RTB2S2 NTB2A 0 R` |
| Output buffer | — | `EOUT VOUT 0 NTA2OUT 0 1` |

---

## Design Procedure

**Step 1 — Identify f₀.**

**Step 2 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 3 — Compute C = 1 / (2π · f₀ · R).** Check C ∈ [1 nF, 100 nF].

**Step 4 — Write two identical Twin-T stages**, using distinct node names for each stage. The output of stage 1 (`NTA1OUT`) feeds both arms of stage 2.

**Step 5 — Add EOUT** at the end reading the final output node.

---

## Worked Example 1

**Specification:** Notch filter, f₀ = 1 kHz, deeper notch than single stage, passband above 4.2 kHz and below 236 Hz.

**Step 1:** f₀ = 1 000 Hz. **Step 2:** R = 10 kΩ. **Step 3:** C = 15.92 nF.

```spice
* 2-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Twin-T notch section
* Twin-T stage 1 — resistive arm
RTA11  VIN      NTA1A   10k
RTA12  NTA1A    NTA1OUT 10k
CTA1S1 NTA1A    0       15.92n
CTA1S2 NTA1A    0       15.92n

* Twin-T stage 1 — capacitive arm
CTB11  VIN      NTB1A   15.92n
CTB12  NTB1A    NTA1OUT 15.92n
RTB1S1 NTB1A    0       10k
RTB1S2 NTB1A    0       10k

* Twin-T stage 2 — resistive arm
RTA21  NTA1OUT  NTA2A   10k
RTA22  NTA2A    NTA2OUT 10k
CTA2S1 NTA2A    0       15.92n
CTA2S2 NTA2A    0       15.92n

* Twin-T stage 2 — capacitive arm
CTB21  NTA1OUT  NTB2A   15.92n
CTB22  NTB2A    NTA2OUT 15.92n
RTB2S1 NTB2A    0       10k
RTB2S2 NTB2A    0       10k

EOUT VOUT  0     NTA2OUT  0  1
.end
```

---

## Worked Example 2

**Specification:** Notch filter, f₀ = 5 kHz, two-stage for deeper rejection.

**Step 1:** f₀ = 5 000 Hz. **Step 2:** R = 10 kΩ. **Step 3:** C = 3.183 nF.

```spice
* 2-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Twin-T stage 1 — resistive arm
RTA11  VIN      NTA1A   10k
RTA12  NTA1A    NTA1OUT 10k
CTA1S1 NTA1A    0       3.183n
CTA1S2 NTA1A    0       3.183n

* Twin-T stage 1 — capacitive arm
CTB11  VIN      NTB1A   3.183n
CTB12  NTB1A    NTA1OUT 3.183n
RTB1S1 NTB1A    0       10k
RTB1S2 NTB1A    0       10k

* Twin-T stage 2 — resistive arm
RTA21  NTA1OUT  NTA2A   10k
RTA22  NTA2A    NTA2OUT 10k
CTA2S1 NTA2A    0       3.183n
CTA2S2 NTA2A    0       3.183n

* Twin-T stage 2 — capacitive arm
CTB21  NTA1OUT  NTB2A   3.183n
CTB22  NTB2A    NTA2OUT 3.183n
RTB2S1 NTB2A    0       10k
RTB2S2 NTB2A    0       10k

EOUT VOUT  0     NTA2OUT  0  1
.end
```

---

## Worked Example 3

**Specification:** Notch filter, f₀ = 400 Hz, two-stage for deeper 400 Hz rejection.

**Step 1:** f₀ = 400 Hz. **Step 2:** R = 20 kΩ. **Step 3:** C = 1/(2π×400×20k) = 19.89 nF.

```spice
* 2-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Twin-T stage 1 — resistive arm
RTA11  VIN      NTA1A   20k
RTA12  NTA1A    NTA1OUT 20k
CTA1S1 NTA1A    0       19.89n
CTA1S2 NTA1A    0       19.89n

* Twin-T stage 1 — capacitive arm
CTB11  VIN      NTB1A   19.89n
CTB12  NTB1A    NTA1OUT 19.89n
RTB1S1 NTB1A    0       20k
RTB1S2 NTB1A    0       20k

* Twin-T stage 2 — resistive arm
RTA21  NTA1OUT  NTA2A   20k
RTA22  NTA2A    NTA2OUT 20k
CTA2S1 NTA2A    0       19.89n
CTA2S2 NTA2A    0       19.89n

* Twin-T stage 2 — capacitive arm
CTB21  NTA1OUT  NTB2A   19.89n
CTB22  NTB2A    NTA2OUT 19.89n
RTB2S1 NTB2A    0       20k
RTB2S2 NTB2A    0       20k

EOUT VOUT  0     NTA2OUT  0  1
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Stage 2 has wrong notch frequency | Stage 2 uses different R or C | Use same R and C for both stages |
| NTA1OUT not connected properly | Stage 2 arms don't start from NTA1OUT | Both RTA21 and CTB21 must start from NTA1OUT |
| Node name collision | Stage 1 and stage 2 share node names | Use distinct names: NTA1A/NTB1A for stage 1; NTA2A/NTB2A for stage 2 |
| No notch | Output node mismatch | EOUT reads NTA2OUT (the stage 2 output), not NTA1OUT |
| Shallow notch at f₀ | Component mismatch | All R values identical; all C values identical |
| C out of range | f₀ too low or R wrong | Adjust R; C = 1/(2πf₀R) |
