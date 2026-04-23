# Band-Pass Filter, Buffered Single-Stage RC (buffered_rc_single)

This document explains how a buffered single-stage passive RC band-pass filter works. An input buffer isolates the source, and an inter-stage buffer isolates the HP section from the LP section so both cutoff frequencies can be set independently. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An input buffer isolates the source from the high-pass section, and a mid-stage buffer between the HP and LP sections eliminates loading between them. Each section can therefore be designed independently using simple first-order formulas.

**Use this topology when:**
- Source impedance is high or unknown.
- Loading between the HP and LP sections would otherwise corrupt the cutoff frequencies.
- Precision passband edges are required.
- Single-stage (−20 dB/decade) roll-off on each side is sufficient.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

CH1  VBUF  nh1    {C_hp}
RH1  nh1   0      {R_hp}

EMID NMID  0     nh1  0  1

RL1  NMID  VOUT   {R_lp}
CL1  VOUT  0      {C_lp}
.end
```

---

## Transfer Function (Independent Sections)

With both buffers, sections are independent:

$$H(j\omega) = \underbrace{\frac{j(f/f_L)}{1+j(f/f_L)}}_{\text{HP, independent}} \times \underbrace{\frac{1}{1+j(f/f_H)}}_{\text{LP, independent}}$$

$$f_L = \frac{1}{2\pi R_{hp} C_{hp}}, \quad f_H = \frac{1}{2\pi R_{lp} C_{lp}}$$

**Passband gain:** 0 dB for f_L << f << f_H.  
**Roll-off:** −20 dB/decade below f_L, −20 dB/decade above f_H.

---

## Key Equations

1. `f_L = 1 / (2π · R_hp · C_hp)`
2. `f_H = 1 / (2π · R_lp · C_lp)`
3. `C_hp = 1 / (2π · f_L · R_hp)`
4. `C_lp = 1 / (2π · f_H · R_lp)`
5. **Lower stopband attenuation:** `A(fs) ≈ 20·log10(f_L/fs)` dB for fs << f_L
6. **Upper stopband attenuation:** `A(fs) ≈ 20·log10(fs/f_H)` dB for fs >> f_H
7. `f_0 = √(f_L × f_H)` — geometric center of passband
8. `BW = f_H − f_L` — bandwidth

---

## Design Procedure

**Step 1 — Identify f_L (lower −3 dB) and f_H (upper −3 dB).**  
Ensure f_H > f_L.

**Step 2 — Design high-pass section independently:**  
Choose R_hp ∈ [1 kΩ, 100 kΩ].  
C_hp = 1/(2π · f_L · R_hp). Verify C_hp ∈ [1 nF, 100 nF].

**Step 3 — Design low-pass section independently:**  
Choose R_lp ∈ [1 kΩ, 100 kΩ] (can be any value — no loading constraint).  
C_lp = 1/(2π · f_H · R_lp). Verify C_lp ∈ [1 nF, 100 nF].

**Step 4 — Write netlist:**  
1. `EBUF VBUF 0 VIN 0 1`
2. HP section: C_hp from VBUF to nh1, R_hp from nh1 to 0
3. `EMID NMID 0 nh1 0 1`
4. LP section: R_lp from NMID to VOUT, C_lp from VOUT to 0

---

## Worked Example 1

**Specification:** Band-pass filter, passband 100 Hz to 5 kHz, high-Z source, stopband ≥ 20 dB below 10 Hz and above 50 kHz.

**Step 1:** f_L = 100 Hz, f_H = 5 000 Hz.

**Step 2:** R_hp = 20 kΩ; C_hp = 1/(2π×100×20k) = 79.58 nF.

**Step 3:** R_lp = 5 kΩ; C_lp = 1/(2π×5000×5k) = 6.366 nF.

**Step 4:** A at 10 Hz: 20·log10(100/10) = 20 dB ✓. A at 50 kHz: 20·log10(50000/5000) = 20 dB ✓.

```spice
* Single-stage passive RC band-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* High-pass section (sets lower cutoff)
CH1  VBUF  nh1    79.58n
RH1  nh1   0      20k

* Mid buffer to isolate HP from LP
EMID NMID  0     nh1  0  1

* Low-pass section (sets upper cutoff)
RL1  NMID  VOUT   5k
CL1  VOUT  0      6.366n
.end
```

---

## Worked Example 2

**Specification:** Band-pass filter, passband 2 kHz to 20 kHz, high-Z source, stopband ≥ 20 dB below 200 Hz and above 200 kHz.

**Step 1:** f_L = 2 000 Hz, f_H = 20 000 Hz.

**Step 2:** R_hp = 10 kΩ; C_hp = 1/(2π×2000×10k) = 7.958 nF.

**Step 3:** R_lp = 4 kΩ; C_lp = 1/(2π×20000×4k) = 1.989 nF ≈ 2.0 nF.

**Verify:** f_L = 1/(2π×10k×7.958n) = 2 000 Hz ✓. f_H = 1/(2π×4k×2.0n) = 19.89 kHz ≈ 20 kHz ✓.

```spice
* Single-stage passive RC band-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* High-pass section (sets lower cutoff)
CH1  VBUF  nh1    7.958n
RH1  nh1   0      10k

* Mid buffer to isolate HP from LP
EMID NMID  0     nh1  0  1

* Low-pass section (sets upper cutoff)
RL1  NMID  VOUT   4k
CL1  VOUT  0      2n
.end
```

---

## Worked Example 3

**Specification:** Band-pass filter, passband 500 Hz to 10 kHz, high-Z source, stopband ≥ 14 dB below 100 Hz and above 50 kHz.

**Step 1:** f_L = 500 Hz, f_H = 10 000 Hz.

**Step 2:** R_hp = 15 kΩ; C_hp = 1/(2π×500×15k) = 21.22 nF.

**Step 3:** R_lp = 5 kΩ; C_lp = 1/(2π×10000×5k) = 3.183 nF.

**Step 5:** A at 100 Hz: 20·log10(500/100) ≈ 14 dB ✓. A at 50 kHz: 20·log10(50000/10000) ≈ 14 dB ✓.

```spice
* Single-stage passive RC band-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* High-pass section (sets lower cutoff)
CH1  VBUF  nh1    21.22n
RH1  nh1   0      15k

* Mid buffer to isolate HP from LP
EMID NMID  0     nh1  0  1

* Low-pass section (sets upper cutoff)
RL1  NMID  VOUT   5k
CL1  VOUT  0      3.183n
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Passband lower than 0 dB | Mid buffer (EMID) missing; LP loads HP | Add `EMID NMID 0 nh1 0 1`; LP R must start from NMID |
| Lower cutoff shifted | EBUF missing; HP section driven by high-Z source | Add EBUF; C_hp must start from VBUF |
| EMID syntax error | Wrong node count or order | `EMID NMID 0 nh1 0 1` — output=NMID, input=nh1 |
| No passband | f_H < f_L | Swap assignments; f_H must be > f_L |
| nh1 floating | R_hp not connected to nh1 or EMID input wrong | Verify: C_hp→nh1, R_hp shunts from nh1, EMID reads nh1 |
| Attenuation too low | Single stage −20 dB/decade only | Use `buffered_rc_multi` for −40 dB/decade |
