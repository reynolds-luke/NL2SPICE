# Notch Filter, Single-Stage Twin-T RC (rc_single)

This document explains how a single-stage passive RC Twin-T notch filter works, how to size its components for a given notch frequency, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

The Twin-T notch filter uses two parallel signal paths that cancel each other at one specific frequency (the notch frequency f₀). Above and below f₀ the filter passes signals with near-unity gain.

**Path 1 (resistive/low-pass arm):** Two resistors R in series with a shunt capacitor of 2C at the midpoint.  
**Path 2 (capacitive/high-pass arm):** Two capacitors C in series with a shunt resistor of R/2 at the midpoint.

At f₀ the impedances of both paths are equal and the signals cancel at the output — producing a deep notch.

**Use this topology when:**
- A specific frequency must be sharply attenuated (e.g., 50/60 Hz mains hum, an interference tone).
- The signal on either side of f₀ should pass unaffected.
- Minimum component count (no op-amps) is acceptable.
- The broad natural bandwidth of the passive Twin-T is acceptable.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

RTA1  VIN   nta    {R}
RTA2  nta   out    {R}
CTAS1 nta   0      {C}
CTAS2 nta   0      {C}

CTB1  VIN   ntb    {C}
CTB2  ntb   out    {C}
RTBS1 ntb   0      {R}
RTBS2 ntb   0      {R}

EOUT VOUT  0     out  0  1
.end
```

---

## Transfer Function

For the symmetric Twin-T (R₁=R₂=R, C₁=C₂=C, C_shunt=2C, R_shunt=R/2):

$$H(s) = \frac{1 + \tau^2 s^2}{1 + 4\tau s + \tau^2 s^2}, \quad \tau = RC$$

**Notch frequency** (zero of H):

$$f_0 = \frac{1}{2\pi R C}$$

At f = f₀: H = 0 (theoretically infinite attenuation, practically 20–60 dB for matched components).

**Passband** (f << f₀ and f >> f₀): |H| → 1 (0 dB).

**−3 dB bandwidth** (the two frequencies where |H| = 1/√2):

Solving |H(jω)|² = 1/2 gives:

$$u^2 - 18u + 1 = 0 \quad \text{where } u = (f/f_0)^2$$

$$f_L = f_0 \times \sqrt{9 - 4\sqrt{5}} \approx 0.2361 \times f_0$$

$$f_H = f_0 \times \sqrt{9 + 4\sqrt{5}} \approx 4.2361 \times f_0$$

These are the **passband −3 dB edges** (where gain recovers to −3 dB from the passband level).

**Q factor:** Q = f₀ / (f_H − f_L) ≈ f₀ / (4 × f₀) = 0.25  
The passive Twin-T is inherently low-Q (wide notch) with Q ≈ 0.25.

---

## Key Equations

1. **Notch frequency:** `f0 = 1 / (2π · R · C)`
2. **Given f0 and R:** `C = 1 / (2π · f0 · R)`
3. **Given f0 and C:** `R = 1 / (2π · f0 · C)`
4. **Lower −3 dB passband edge:** `f_L ≈ 0.2361 × f0`
5. **Upper −3 dB passband edge:** `f_H ≈ 4.2361 × f0`
6. **Notch bandwidth (−3 dB):** `BW ≈ 4 × f0`
7. **Q factor:** `Q ≈ 0.25` (passive Twin-T)

---

## SPICE Component Mapping

| Twin-T element | SPICE implementation |
|----------------|---------------------|
| Resistive arm: R series (×2) | `RTA1 VIN nta R` and `RTA2 nta out R` |
| Resistive arm: 2C shunt | `CTAS1 nta 0 C` and `CTAS2 nta 0 C` (two C in parallel = 2C) |
| Capacitive arm: C series (×2) | `CTB1 VIN ntb C` and `CTB2 ntb out C` |
| Capacitive arm: R/2 shunt | `RTBS1 ntb 0 R` and `RTBS2 ntb 0 R` (two R in parallel = R/2) |
| Output buffer | `EOUT VOUT 0 out 0 1` |

All four paths drive the same node `out`. EOUT reads `out` and drives VOUT.

---

## Design Procedure

**Step 1 — Identify the notch frequency f₀.**

**Step 2 — Check if the notch depth and bandwidth meet spec.**  
The passive Twin-T has Q ≈ 0.25 (wide notch, BW ≈ 4f₀). For a narrower notch, use an active topology (not in this project's scope). For a deeper notch, use `rc_multi` (two cascaded Twin-T stages).

**Step 3 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 4 — Compute C = 1 / (2π · f₀ · R).**  
Check C ∈ [1 nF, 100 nF].

**Step 5 — Build the SPICE netlist** with the component mapping above. Both arms share the node name `out` before the EOUT buffer.

---

## Worked Example 1

**Specification:** Notch filter, f₀ = 1 kHz (reject 1 kHz interference), passband passes DC–200 Hz and 4 kHz–∞.

**Step 1:** f₀ = 1 000 Hz.

**Step 2:** f_L ≈ 0.2361 × 1000 = 236 Hz; f_H ≈ 4.2361 × 1000 = 4 236 Hz.  
DC–200 Hz is below 236 Hz (very close); 4 kHz is just below 4 236 Hz (marginal). Q ≈ 0.25.

**Step 3:** R = 10 kΩ.

**Step 4:** C = 1/(2π × 1000 × 10000) = 15.92 nF.

```spice
* Single-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Twin-T notch section
* Resistive arm
RTA1 VIN   nta    10k
RTA2 nta   out    10k
CTAS1 nta  0      15.92n
CTAS2 nta  0      15.92n

* Capacitive arm
CTB1 VIN   ntb    15.92n
CTB2 ntb   out    15.92n
RTBS1 ntb  0      10k
RTBS2 ntb  0      10k

EOUT VOUT  0     out  0  1
.end
```

---

## Worked Example 2

**Specification:** Notch filter, f₀ = 50 Hz (reject mains hum), passband above 212 Hz and below 11.8 Hz.

**Step 1:** f₀ = 50 Hz.

**Step 2:** f_L ≈ 11.8 Hz, f_H ≈ 211.8 Hz. BW ≈ 200 Hz.

**Step 3:** R = 50 kΩ (large R chosen to get C in range).

**Step 4:** C = 1/(2π × 50 × 50000) = 63.66 nF ✓ (< 100 nF).

```spice
* Single-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Twin-T notch section
* Resistive arm
RTA1 VIN   nta    50k
RTA2 nta   out    50k
CTAS1 nta  0      63.66n
CTAS2 nta  0      63.66n

* Capacitive arm
CTB1 VIN   ntb    63.66n
CTB2 ntb   out    63.66n
RTBS1 ntb  0      50k
RTBS2 ntb  0      50k

EOUT VOUT  0     out  0  1
.end
```

---

## Worked Example 3

**Specification:** Notch filter, f₀ = 5 kHz, passband passes DC–1.18 kHz and 21.2 kHz–∞.

**Step 1:** f₀ = 5 000 Hz.

**Step 2:** f_L ≈ 0.2361 × 5000 = 1 180 Hz; f_H ≈ 4.2361 × 5000 = 21 180 Hz.

**Step 3:** R = 10 kΩ.

**Step 4:** C = 1/(2π × 5000 × 10000) = 3.183 nF ✓.

```spice
* Single-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Twin-T notch section
* Resistive arm
RTA1 VIN   nta    10k
RTA2 nta   out    10k
CTAS1 nta  0      3.183n
CTAS2 nta  0      3.183n

* Capacitive arm
CTB1 VIN   ntb    3.183n
CTB2 ntb   out    3.183n
RTBS1 ntb  0      10k
RTBS2 ntb  0      10k

EOUT VOUT  0     out  0  1
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Notch frequency wrong | Incorrect R or C | Recalculate: f0 = 1/(2πRC) |
| No notch visible | Arm components unequal (mismatch) | Verify both arms use exactly the same R and C values |
| Output VOUT is 0 V everywhere | EOUT missing or `out` node not reached by both arms | Add EOUT; confirm RTA2 and CTB2 both connect to `out` |
| `nta` or `ntb` floating | Shunt components missing | Add CTAS1+CTAS2 to nta, RTBS1+RTBS2 to ntb |
| Notch depth shallow | Component tolerances, or simulation nodes misnamed | Re-check all node names for consistency |
| Notch too wide | Q = 0.25 is inherent in passive Twin-T | Use active filter or feedback to boost Q (outside this topology) |
| C > 100 nF | f₀ low or R large | Decrease R (try 10–30 kΩ for low frequencies) |
| C < 1 nF | f₀ high or R small | Increase R toward 100 kΩ |
