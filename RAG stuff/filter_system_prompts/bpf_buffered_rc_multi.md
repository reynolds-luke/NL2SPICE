# Band-Pass Filter, Two-Stage Buffered RC (buffered_rc_multi)

This document explains how a two-stage buffered passive RC band-pass filter works (input buffer + two HP stages + inter-stage buffer + two LP stages), how to size components with loading corrections, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An input buffer isolates the source, two high-pass stages set the lower cutoff, a mid-stage buffer separates the HP and LP sections, and two low-pass stages set the upper cutoff. Buffers between major sections eliminate inter-section loading. Within each two-stage HP or LP group there is no inter-stage buffer, so the loaded two-stage formula applies within each section.

**Use this topology when:**
- Source impedance is high or unknown.
- Steep −40 dB/decade roll-off on both sides is needed.
- Precise, load-independent cutoff frequencies are critical.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

CH1  VBUF  nh1    {C_hp}
RH1  nh1   0      {R_hp}
CH2  nh1   nh2    {C_hp}
RH2  nh2   0      {R_hp}

EMID NMID  0     nh2  0  1

RL1  NMID  nl1    {R_lp}
CL1  nl1   0      {C_lp}
RL2  nl1   VOUT   {R_lp}
CL2  VOUT  0      {C_lp}
.end
```

---

## Transfer Function

The input buffer and mid-stage buffer make each section independent.

**High-pass section** (2 stages, R_hp, C_hp, loaded — same as rc_multi HP):

$$f_L = 2.672 \times \frac{1}{2\pi R_{hp} C_{hp}}$$

$$C_{hp} = \frac{2.672}{2\pi \cdot f_L \cdot R_{hp}}$$

**Low-pass section** (2 stages, R_lp, C_lp, loaded — same as rc_multi LP):

$$f_H = \frac{0.3743}{2\pi R_{lp} C_{lp}}$$

$$C_{lp} = \frac{1}{2\pi \cdot 2.672 \cdot f_H \cdot R_{lp}}$$

**Roll-off:** −40 dB/decade below f_L, −40 dB/decade above f_H.  
**Passband gain:** 0 dB (mid-band).

---

## Key Equations

1. `C_hp = 2.672 / (2π · f_L · R_hp)`
2. `C_lp = 1 / (2π · 2.672 · f_H · R_lp)`
3. `f_L = 2.672 / (2π · R_hp · C_hp)`  (verification)
4. `f_H = 1 / (2π · 2.672 · R_lp · C_lp)`  (verification)
5. Lower stop attenuation: `A(fs) ≈ 40·log10(f_L/fs)` dB
6. Upper stop attenuation: `A(fs) ≈ 40·log10(fs/f_H)` dB
7. `f_0 = √(f_L × f_H)`
8. `BW = f_H − f_L`

---

## Design Procedure

**Step 1 — Identify f_L and f_H.**

**Step 2 — HP section:**  
Choose R_hp ∈ [1 kΩ, 100 kΩ].  
C_hp = 2.672/(2π · f_L · R_hp). Check C_hp ∈ [1 nF, 100 nF].

**Step 3 — LP section:**  
Choose R_lp ∈ [1 kΩ, 100 kΩ].  
C_lp = 1/(2π · 2.672 · f_H · R_lp). Check C_lp ∈ [1 nF, 100 nF].

**Step 4 — Write netlist:**  
1. EBUF VBUF 0 VIN 0 1
2. CH1 (VBUF→nh1), RH1 (nh1→0)
3. CH2 (nh1→nh2), RH2 (nh2→0)
4. EMID NMID 0 nh2 0 1
5. RL1 (NMID→nl1), CL1 (nl1→0)
6. RL2 (nl1→VOUT), CL2 (VOUT→0)

---

## Worked Example 1

**Specification:** Band-pass filter, passband 300 Hz to 3 kHz, high-Z source, stopband ≥ 40 dB below 30 Hz and above 30 kHz.

**Step 1:** f_L = 300 Hz, f_H = 3 000 Hz.

**Step 2 HP:** R_hp = 10 kΩ; C_hp = 2.672/(2π×300×10k) = 141.7 nF — too large.  
Use R_hp = 30 kΩ: C_hp = 2.672/(2π×300×30k) = 47.23 nF ✓.

**Step 3 LP:** R_lp = 10 kΩ; C_lp = 1/(2π×2.672×3000×10k) = 1.985 nF ≈ 2.0 nF ✓.

```spice
* 2-stage passive RC band-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* High-pass section (sets lower cutoff ~300 Hz)
CH1  VBUF  nh1    47.23n
RH1  nh1   0      30k
CH2  nh1   nh2    47.23n
RH2  nh2   0      30k

* Mid buffer to isolate HP from LP
EMID NMID  0     nh2  0  1

* Low-pass section (sets upper cutoff ~3 kHz)
RL1  NMID  nl1    10k
CL1  nl1   0      2n
RL2  nl1   VOUT   10k
CL2  VOUT  0      2n
.end
```

---

## Worked Example 2

**Specification:** Band-pass filter, passband 1 kHz to 10 kHz, high-Z source, stopband ≥ 40 dB below 100 Hz and above 100 kHz.

**Step 2 HP:** R_hp = 10 kΩ; C_hp = 2.672/(2π×1000×10k) = 42.52 nF ✓.

**Step 3 LP:** R_lp = 1 kΩ; C_lp = 1/(2π×2.672×10000×1k) = 5.957 nF ✓.

```spice
* 2-stage passive RC band-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* High-pass section (sets lower cutoff ~1 kHz)
CH1  VBUF  nh1    42.52n
RH1  nh1   0      10k
CH2  nh1   nh2    42.52n
RH2  nh2   0      10k

* Mid buffer to isolate HP from LP
EMID NMID  0     nh2  0  1

* Low-pass section (sets upper cutoff ~10 kHz)
RL1  NMID  nl1    1k
CL1  nl1   0      5.957n
RL2  nl1   VOUT   1k
CL2  VOUT  0      5.957n
.end
```

---

## Worked Example 3

**Specification:** Band-pass filter, passband 500 Hz to 5 kHz, high-Z source, stopband ≥ 40 dB below 50 Hz and above 50 kHz.

**Step 2 HP:** R_hp = 10 kΩ; C_hp = 2.672/(2π×500×10k) = 85.02 nF ✓.

**Step 3 LP:** R_lp = 2 kΩ; C_lp = 1/(2π×2.672×5000×2k) = 5.957 nF ✓.

```spice
* 2-stage passive RC band-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* High-pass section (sets lower cutoff ~500 Hz)
CH1  VBUF  nh1    85.02n
RH1  nh1   0      10k
CH2  nh1   nh2    85.02n
RH2  nh2   0      10k

* Mid buffer to isolate HP from LP
EMID NMID  0     nh2  0  1

* Low-pass section (sets upper cutoff ~5 kHz)
RL1  NMID  nl1    2k
CL1  nl1   0      5.957n
RL2  nl1   VOUT   2k
CL2  VOUT  0      5.957n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Lower cutoff wrong | Single-stage HP formula used | C_hp = 2.672/(2π·f_L·R_hp) |
| Upper cutoff wrong | Single-stage LP formula used | C_lp = 1/(2π·2.672·f_H·R_lp) |
| Passband gain < 0 dB | EMID missing; LP loads HP | Add `EMID NMID 0 nh2 0 1`; RL1 starts from NMID |
| Source loading | EBUF missing; CH1 from VIN not VBUF | Add EBUF; CH1 starts from VBUF |
| C_hp > 100 nF | f_L is low, R_hp too small | Increase R_hp (30–100 kΩ) |
| C_lp < 1 nF | f_H high, R_lp too small | Increase R_lp |
| nh2 floating | EMID input or RH2 not connected to nh2 | Verify: CH2→nh2, RH2 shunt from nh2, EMID reads nh2 |
