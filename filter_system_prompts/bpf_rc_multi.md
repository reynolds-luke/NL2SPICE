# Band-Pass Filter, Two-Stage Passive RC (rc_multi)

This document explains how a two-stage passive RC band-pass filter works (two HP stages followed by two LP stages), how to apply the loading correction when sizing components, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

Two high-pass stages are cascaded followed by two low-pass stages, all without op-amp buffers. The HP stages set the lower cutoff, the LP stages set the upper cutoff. Stages within each section interact through loading, so the two-stage correction factors apply to each section independently.

**Use this topology when:**
- Steeper roll-off on both sides (≈ −40 dB/decade per side) is needed.
- No op-amps are available.
- Source impedance is low.
- The band ratio f_H/f_L is large enough that inter-section loading is manageable.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

CH1  VIN   nh1    {C_hp}
RH1  nh1   0      {R_hp}
CH2  nh1   nh2    {C_hp}
RH2  nh2   0      {R_hp}

RL1  nh2   nl1    {R_lp}
CL1  nl1   0      {C_lp}
RL2  nl1   VOUT   {R_lp}
CL2  VOUT  0      {C_lp}
.end
```

---

## Transfer Function

Each section is analysed separately using the two-stage loaded RC formula.

**High-pass section** (2 identical stages R_hp, C_hp, no buffer between HP stages):

$$f_L = 2.672 \times f_{c,hp\text{-stage}} = 2.672 \times \frac{1}{2\pi R_{hp} C_{hp}}$$

Design equation: to achieve target f_L:

$$f_{c,hp\text{-stage}} = 0.3743 \times f_L$$

$$C_{hp} = \frac{2.672}{2\pi \cdot f_L \cdot R_{hp}}$$

**Low-pass section** (2 identical stages R_lp, C_lp, no buffer between LP stages):

$$f_H = 0.3743 \times f_{c,lp\text{-stage}} = 0.3743 \times \frac{1}{2\pi R_{lp} C_{lp}}$$

Design equation: to achieve target f_H:

$$f_{c,lp\text{-stage}} = 2.672 \times f_H$$

$$C_{lp} = \frac{1}{2\pi \cdot 2.672 \cdot f_H \cdot R_{lp}}$$

**Roll-off:** ≈ −40 dB/decade below f_L, ≈ −40 dB/decade above f_H.

---

## Key Equations

**High-pass section (lower cutoff f_L):**
1. `C_hp = 2.672 / (2π · f_L · R_hp)` — design equation
2. `f_{c,hp-stage} = 1/(2π·R_hp·C_hp)` — individual stage corner
3. Attenuation at fs < f_L: `A(fs) ≈ 40·log10(f_L/fs)` dB

**Low-pass section (upper cutoff f_H):**
4. `C_lp = 1 / (2π · 2.672 · f_H · R_lp)` — design equation
5. `f_{c,lp-stage} = 1/(2π·R_lp·C_lp)` — individual stage corner
6. Attenuation at fs > f_H: `A(fs) ≈ 40·log10(fs/f_H)` dB

**Both sections:**
7. `f_H > f_L` required
8. `f_0 = √(f_L × f_H)` — geometric center
9. `BW = f_H − f_L` — bandwidth

---

## Design Procedure

**Step 1 — Identify f_L and f_H.**

**Step 2 — Verify band ratio:** Confirm f_H > f_L and that 40 dB/decade slopes meet specs.

**Step 3 — Design HP section:**  
Choose R_hp ∈ [1 kΩ, 100 kΩ].  
C_hp = 2.672/(2π · f_L · R_hp). Check C_hp ∈ [1 nF, 100 nF].

**Step 4 — Design LP section:**  
Choose R_lp ∈ [1 kΩ, 100 kΩ].  
C_lp = 1/(2π · 2.672 · f_H · R_lp). Check C_lp ∈ [1 nF, 100 nF].

**Step 5 — Write netlist:**  
HP: CH1 (VIN→nh1), RH1 (nh1→0), CH2 (nh1→nh2), RH2 (nh2→0).  
LP: RL1 (nh2→nl1), CL1 (nl1→0), RL2 (nl1→VOUT), CL2 (VOUT→0).

---

## Worked Example 1

**Specification:** Band-pass filter, passband 200 Hz to 2 kHz, stopband ≥ 40 dB below 20 Hz and above 20 kHz.

**Step 1:** f_L = 200 Hz, f_H = 2 000 Hz.

**Step 2:** 40·log10(200/20) = 40 dB ✓; 40·log10(20000/2000) = 40 dB ✓ (asymptote).

**Step 3 HP:** R_hp = 10 kΩ; C_hp = 2.672/(2π×200×10k) = 212.6 nF.  
C_hp > 100 nF — need larger R_hp: use R_hp = 30 kΩ.  
C_hp = 2.672/(2π×200×30k) = 70.87 nF ✓.

**Step 4 LP:** R_lp = 10 kΩ; C_lp = 1/(2π×2.672×2000×10k) = 2.978 nF ✓.

```spice
* 2-stage passive RC band-pass filter
V1   VIN   0     AC 1

* High-pass section (sets lower cutoff ~200 Hz)
CH1  VIN   nh1    70.87n
RH1  nh1   0      30k
CH2  nh1   nh2    70.87n
RH2  nh2   0      30k

* Low-pass section (sets upper cutoff ~2 kHz)
RL1  nh2   nl1    10k
CL1  nl1   0      2.978n
RL2  nl1   VOUT   10k
CL2  VOUT  0      2.978n
.end
```

---

## Worked Example 2

**Specification:** Band-pass filter, passband 500 Hz to 5 kHz, stopband ≥ 40 dB below 50 Hz and above 50 kHz.

**Step 1:** f_L = 500 Hz, f_H = 5 000 Hz.

**Step 3 HP:** R_hp = 10 kΩ; C_hp = 2.672/(2π×500×10k) = 85.02 nF ✓.

**Step 4 LP:** R_lp = 10 kΩ; C_lp = 1/(2π×2.672×5000×10k) = 1.192 nF ≈ 1.2 nF ✓.

```spice
* 2-stage passive RC band-pass filter
V1   VIN   0     AC 1

* High-pass section (sets lower cutoff ~500 Hz)
CH1  VIN   nh1    85.02n
RH1  nh1   0      10k
CH2  nh1   nh2    85.02n
RH2  nh2   0      10k

* Low-pass section (sets upper cutoff ~5 kHz)
RL1  nh2   nl1    10k
CL1  nl1   0      1.2n
RL2  nl1   VOUT   10k
CL2  VOUT  0      1.2n
.end
```

---

## Worked Example 3

**Specification:** Band-pass filter, passband 1 kHz to 10 kHz, stopband ≥ 40 dB below 100 Hz and above 100 kHz.

**Step 3 HP:** R_hp = 10 kΩ; C_hp = 2.672/(2π×1000×10k) = 42.52 nF ✓.

**Step 4 LP:** R_lp = 1 kΩ; C_lp = 1/(2π×2.672×10000×1k) = 5.957 nF ✓.

```spice
* 2-stage passive RC band-pass filter
V1   VIN   0     AC 1

* High-pass section (sets lower cutoff ~1 kHz)
CH1  VIN   nh1    42.52n
RH1  nh1   0      10k
CH2  nh1   nh2    42.52n
RH2  nh2   0      10k

* Low-pass section (sets upper cutoff ~10 kHz)
RL1  nh2   nl1    1k
CL1  nl1   0      5.957n
RL2  nl1   VOUT   1k
CL2  VOUT  0      5.957n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Lower cutoff wrong | Single-stage formula used for HP (missing 2.672 correction) | C_hp = 2.672/(2π·f_L·R_hp) |
| Upper cutoff wrong | Single-stage formula used for LP (missing 2.672 correction) | C_lp = 1/(2π·2.672·f_H·R_lp) |
| Passband gain low | LP section loads HP output node | Increase R_lp / decrease R_hp, or use `buffered_rc_multi` |
| C_hp > 100 nF | f_L low, R_hp too small | Increase R_hp (e.g., 30–100 kΩ) |
| C_lp < 1 nF | f_H high, R_lp too small | Increase R_lp |
| nh2 floating | No connection between HP and LP sections | RL1 connects FROM nh2, not nh1 |
| No passband | f_H ≤ f_L | Verify assignments; ensure HP corner < LP corner |
