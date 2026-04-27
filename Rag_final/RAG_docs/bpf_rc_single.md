# Band-Pass Filter, Single-Stage RC (rc_single)

This document explains how a single-stage passive RC band-pass filter works (a cascaded HP + LP section), how to choose component values for given lower and upper cutoff frequencies, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

A single-stage passive RC band-pass filter is formed by cascading a high-pass section (sets the lower −3 dB cutoff) directly into a low-pass section (sets the upper −3 dB cutoff). There is no buffer between the two sections, so the low-pass section's input impedance loads the high-pass section.

**Use this topology when:**
- A passband between two cutoff frequencies is needed.
- Minimum component count (no op-amps) is acceptable.
- The ratio fc_high / fc_low > ~10 (wider band) reduces loading error.
- Source impedance is low.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

CH1  VIN   nh1    {C_hp}
RH1  nh1   0      {R_hp}

RL1  nh1   VOUT   {R_lp}
CL1  VOUT  0      {C_lp}
.end
```

---

## Transfer Function (Ideal, No Loading)

If R_lp >> R_hp (minimal loading), the sections are approximately independent:

$$H(j\omega) \approx \underbrace{\frac{j(f/f_L)}{1+j(f/f_L)}}_{\text{HP section}} \times \underbrace{\frac{1}{1+j(f/f_H)}}_{\text{LP section}}$$

where:

$$f_L = \frac{1}{2\pi R_{hp} C_{hp}} \quad \text{(lower −3 dB cutoff)}$$

$$f_H = \frac{1}{2\pi R_{lp} C_{lp}} \quad \text{(upper −3 dB cutoff)}$$

**Passband:** f_L < f < f_H (gain ≈ 0 dB within the band, if the band is wide enough).

**Passband gain at mid-band** (f_L << f << f_H): |H| → 1 (0 dB) for an ideal two-section cascade.

**With loading** (R_lp is comparable to R_hp): The LP section shunts the HP section output, lowering the effective R_hp and shifting both cutoffs. Use wider separation (f_H/f_L ≥ 10) or use the buffered topology to eliminate this.

**Roll-off:**
- Below f_L: −20 dB/decade (high-pass slope)
- Above f_H: −20 dB/decade (low-pass slope)

**Attenuation at stopband frequency fs < f_L:**

$$A(f_s) \approx 20\log_{10}\!\left(\frac{f_L}{f_s}\right) \text{ dB}$$

**Attenuation at stopband frequency fs > f_H:**

$$A(f_s) \approx 20\log_{10}\!\left(\frac{f_s}{f_H}\right) \text{ dB}$$

---

## Key Equations

1. `f_L = 1 / (2π · R_hp · C_hp)`  — lower cutoff (high-pass section)
2. `f_H = 1 / (2π · R_lp · C_lp)`  — upper cutoff (low-pass section)
3. `C_hp = 1 / (2π · f_L · R_hp)`
4. `C_lp = 1 / (2π · f_H · R_lp)`
5. **Constraint:** `f_H > f_L` (passband must exist)
6. **Loading rule of thumb:** `R_lp ≥ 10 × R_hp` for minimal loading effect
7. Lower stopband attenuation: `A(fs) ≈ 20·log10(f_L/fs)` for fs << f_L
8. Upper stopband attenuation: `A(fs) ≈ 20·log10(fs/f_H)` for fs >> f_H
9. **Bandwidth:** `BW = f_H − f_L`
10. **Center frequency:** `f_0 = √(f_L × f_H)` (geometric mean)

---

## Design Procedure

**Step 1 — Identify f_L (lower −3 dB) and f_H (upper −3 dB).**

**Step 2 — Confirm the passband is achievable:** f_H > f_L.

**Step 3 — Design the high-pass section:**  
Choose R_hp ∈ [1 kΩ, 100 kΩ].  
Compute C_hp = 1/(2π · f_L · R_hp). Check C_hp ∈ [1 nF, 100 nF].

**Step 4 — Design the low-pass section:**  
Choose R_lp ≥ R_hp (preferably R_lp ≥ 10 × R_hp to reduce loading).  
Compute C_lp = 1/(2π · f_H · R_lp). Check C_lp ∈ [1 nF, 100 nF].  
If both constraints cannot be met simultaneously, relax the loading ratio or use the buffered topology.

**Step 5 — Verify stopband specs** at the required frequencies.

---

## Worked Example 1

**Specification:** Band-pass filter, passband 200 Hz to 2 kHz, stopband ≥ 20 dB below 20 Hz and above 20 kHz.

**Step 1:** f_L = 200 Hz, f_H = 2 000 Hz.

**Step 2:** f_H/f_L = 10 ✓ (band ratio ≥ 10, loading manageable).

**Step 3:** R_hp = 10 kΩ; C_hp = 1/(2π×200×10k) = 79.58 nF.

**Step 4:** R_lp = 10 kΩ (same; loading may shift cutoffs slightly — acceptable for demo).  
C_lp = 1/(2π×2000×10k) = 7.958 nF.

**Step 5:** Lower stop at 20 Hz: A ≈ 20·log10(200/20) = 20 dB ✓.  
Upper stop at 20 kHz: A ≈ 20·log10(20000/2000) = 20 dB ✓.

```spice
* Single-stage passive RC band-pass filter
V1   VIN   0     AC 1

* High-pass section (sets lower cutoff)
C_hp VIN   nh1    79.58n
R_hp nh1   0      10k

* Low-pass section (sets upper cutoff)
R_lp nh1   VOUT   10k
C_lp VOUT  0      7.958n
.end
```

---

## Worked Example 2

**Specification:** Band-pass filter, passband 1 kHz to 10 kHz, stopband ≥ 20 dB below 100 Hz and above 100 kHz.

**Step 1:** f_L = 1 000 Hz, f_H = 10 000 Hz.

**Step 2:** f_H/f_L = 10 ✓.

**Step 3:** R_hp = 10 kΩ; C_hp = 1/(2π×1000×10k) = 15.92 nF.

**Step 4:** R_lp = 10 kΩ; C_lp = 1/(2π×10000×10k) = 1.592 nF.

**Step 5:** Lower stop 100 Hz: 20·log10(1000/100) = 20 dB ✓.  
Upper stop 100 kHz: 20·log10(100000/10000) = 20 dB ✓.

```spice
* Single-stage passive RC band-pass filter
V1   VIN   0     AC 1

* High-pass section (sets lower cutoff)
CH1  VIN   nh1    15.92n
RH1  nh1   0      10k

* Low-pass section (sets upper cutoff)
RL1  nh1   VOUT   10k
CL1  VOUT  0      1.592n
.end
```

---

## Worked Example 3

**Specification:** Band-pass filter, passband 500 Hz to 5 kHz, stopband ≥ 14 dB below 100 Hz and above 25 kHz.

**Step 1:** f_L = 500 Hz, f_H = 5 000 Hz.

**Step 2:** f_H/f_L = 10 ✓.

**Step 3:** R_hp = 10 kΩ; C_hp = 1/(2π×500×10k) = 31.83 nF.

**Step 4:** R_lp = 10 kΩ; C_lp = 1/(2π×5000×10k) = 3.183 nF.

**Step 5:** Lower stop 100 Hz: 20·log10(500/100) ≈ 14 dB ✓.  
Upper stop 25 kHz: 20·log10(25000/5000) ≈ 14 dB ✓.

```spice
* Single-stage passive RC band-pass filter
V1   VIN   0     AC 1

* High-pass section (sets lower cutoff)
CH1  VIN   nh1    31.83n
RH1  nh1   0      10k

* Low-pass section (sets upper cutoff)
RL1  nh1   VOUT   10k
CL1  VOUT  0      3.183n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Passband gain well below 0 dB | LP section loads HP section; R_lp ≈ R_hp | Use `buffered_rc_single` (mid buffer isolates sections) |
| Lower cutoff shifted up | LP shunts HP node, lowers effective R_hp | Increase R_lp, or use buffered topology |
| Upper cutoff shifted down | HP loading reduces voltage at LP input | Increase R_lp relative to R_hp |
| No passband visible | f_H ≤ f_L | Swap section assignments; ensure f_H > f_L |
| Attenuation insufficient on one side | Single-stage only −20 dB/decade per side | Use `rc_multi` or `buffered_rc_multi` for steeper roll-off |
| C_hp > 100 nF | f_L very low or R_hp too large | Reduce R_hp toward 1 kΩ |
| C_lp < 1 nF | f_H very high or R_lp too small | Increase R_lp toward 100 kΩ |
