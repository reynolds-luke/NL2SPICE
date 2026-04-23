# Notch Filter, Two-Stage Buffered Twin-T RC (buffered_rc_multi)

This document explains how a two-stage buffered passive RC Twin-T notch filter works, how input and inter-stage buffers isolate the stages for maximum notch depth, and how to write its SPICE netlist. See `base_prompt.md` for general netlist format rules.

---

## Topology Description

An ideal unity-gain input buffer isolates the source from the first Twin-T stage. A mid-stage buffer between Twin-T stage 1 and Twin-T stage 2 isolates the stages from each other. Both stages are tuned to the same notch frequency f₀. This topology combines the deeper notch of a two-stage cascade with source and inter-stage isolation from the buffers.

**Use this topology when:**
- Source impedance is high or unknown.
- Maximum notch depth and sharpest skirts are required.
- Both stages must be independent to avoid inter-stage loading that would detune the notch.

---

## Circuit Diagram

```spice
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

RTA11  VBUF     NTA1A    {R}
RTA12  NTA1A    NTA1OUT  {R}
CTA1S1 NTA1A    0        {C}
CTA1S2 NTA1A    0        {C}

CTB11  VBUF     NTB1A    {C}
CTB12  NTB1A    NTA1OUT  {C}
RTB1S1 NTB1A    0        {R}
RTB1S2 NTB1A    0        {R}

EMID NMID  0     NTA1OUT  0  1

RTA21  NMID     NTA2A    {R}
RTA22  NTA2A    NTB2OUT  {R}
CTA2S1 NTA2A    0        {C}
CTA2S2 NTA2A    0        {C}

CTB21  NMID     NTB2A    {C}
CTB22  NTB2A    NTB2OUT  {C}
RTB2S1 NTB2A    0        {R}
RTB2S2 NTB2A    0        {R}

EOUT VOUT  0     NTB2OUT  0  1
.end
```

---

## Transfer Function

With full buffer isolation, each stage is truly independent:

$$H(s) = H_1(s) \times H_2(s) = \left(\frac{1 + \tau^2 s^2}{1 + 4\tau s + \tau^2 s^2}\right)^2$$

**Notch frequency:** `f₀ = 1/(2πRC)` — same for both stages.

Both stages use identical R and C.

**Key passband edges (two cascaded, approximate):**
- Edges shift inward slightly compared to single stage; use single-stage formulas as approximation.
- `f_L ≈ 0.25 × f₀`, `f_H ≈ 4 × f₀` (rough estimates; exact value slightly inside these).

---

## Key Equations

1. `f0 = 1 / (2π · R · C)`
2. `C = 1 / (2π · f0 · R)`
3. `f_L ≈ 0.2361 × f0`  (lower passband −3 dB, approximate for 2 stages)
4. `f_H ≈ 4.2361 × f0`  (upper passband −3 dB, approximate for 2 stages)
5. Both stages must use the same R and C

---

## SPICE Component Naming (Two Buffered Stages)

Stage 1 (prefix `A`): nodes `NTA1A`, `NTB1A`, `NTA1OUT`  
Stage 2 (prefix `B`): nodes `NTA2A`, `NTB2A`, `NTB2OUT`  
Stage 2 is driven by `NMID` (mid buffer output).

---

## Design Procedure

**Step 1 — Identify f₀.**

**Step 2 — Choose R ∈ [1 kΩ, 100 kΩ].**

**Step 3 — C = 1 / (2π · f₀ · R).** Check C ∈ [1 nF, 100 nF].

**Step 4 — Write netlist:**  
1. `EBUF VBUF 0 VIN 0 1`
2. Stage 1 Twin-T from VBUF → NTA1OUT
3. `EMID NMID 0 NTA1OUT 0 1`
4. Stage 2 Twin-T from NMID → NTB2OUT
5. `EOUT VOUT 0 NTB2OUT 0 1`

---

## Worked Example 1

**Specification:** Notch filter, f₀ = 60 Hz, high-Z source, maximum notch depth needed.

**Step 1:** f₀ = 60 Hz. **Step 2:** R = 40 kΩ. **Step 3:** C = 1/(2π×60×40k) = 66.31 nF ✓.

```spice
* 2-stage passive RC notch filter buffered (Twin-T)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Stage 1
* Twin-T stage 1 — resistive arm
RTA11  VBUF     NTA1A    40k
RTA12  NTA1A    NTA1OUT  40k
CTA1S1 NTA1A    0        66.31n
CTA1S2 NTA1A    0        66.31n

* Twin-T stage 1 — capacitive arm
CTB11  VBUF     NTB1A    66.31n
CTB12  NTB1A    NTA1OUT  66.31n
RTB1S1 NTB1A    0        40k
RTB1S2 NTB1A    0        40k

* Mid buffer to isolate stage 1 from stage 2
EMID NMID  0     NTA1OUT  0  1

* Stage 2
* Twin-T stage 2 — resistive arm
RTA21  NMID     NTA2A    40k
RTA22  NTA2A    NTB2OUT  40k
CTA2S1 NTA2A    0        66.31n
CTA2S2 NTA2A    0        66.31n

* Twin-T stage 2 — capacitive arm
CTB21  NMID     NTB2A    66.31n
CTB22  NTB2A    NTB2OUT  66.31n
RTB2S1 NTB2A    0        40k
RTB2S2 NTB2A    0        40k

EOUT VOUT  0     NTB2OUT  0  1
.end
```

---

## Worked Example 2

**Specification:** Notch filter, f₀ = 1 kHz, high-Z source, deep notch.

**Step 1:** f₀ = 1 000 Hz. **Step 2:** R = 10 kΩ. **Step 3:** C = 15.92 nF.

```spice
* 2-stage passive RC notch filter buffered (Twin-T)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Stage 1
* Twin-T stage 1 — resistive arm
RTA11  VBUF     NTA1A    10k
RTA12  NTA1A    NTA1OUT  10k
CTA1S1 NTA1A    0        15.92n
CTA1S2 NTA1A    0        15.92n

* Twin-T stage 1 — capacitive arm
CTB11  VBUF     NTB1A    15.92n
CTB12  NTB1A    NTA1OUT  15.92n
RTB1S1 NTB1A    0        10k
RTB1S2 NTB1A    0        10k

* Mid buffer to isolate stage 1 from stage 2
EMID NMID  0     NTA1OUT  0  1

* Stage 2
* Twin-T stage 2 — resistive arm
RTA21  NMID     NTA2A    10k
RTA22  NTA2A    NTB2OUT  10k
CTA2S1 NTA2A    0        15.92n
CTA2S2 NTA2A    0        15.92n

* Twin-T stage 2 — capacitive arm
CTB21  NMID     NTB2A    15.92n
CTB22  NTB2A    NTB2OUT  15.92n
RTB2S1 NTB2A    0        10k
RTB2S2 NTB2A    0        10k

EOUT VOUT  0     NTB2OUT  0  1
.end
```

---

## Worked Example 3

**Specification:** Notch filter, f₀ = 10 kHz, high-Z source, deep rejection needed.

**Step 1:** f₀ = 10 000 Hz. **Step 2:** R = 5 kΩ. **Step 3:** C = 1/(2π×10000×5000) = 3.183 nF ✓.

```spice
* 2-stage passive RC notch filter buffered (Twin-T)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Stage 1
* Twin-T stage 1 — resistive arm
RTA11  VBUF     NTA1A    5k
RTA12  NTA1A    NTA1OUT  5k
CTA1S1 NTA1A    0        3.183n
CTA1S2 NTA1A    0        3.183n

* Twin-T stage 1 — capacitive arm
CTB11  VBUF     NTB1A    3.183n
CTB12  NTB1A    NTA1OUT  3.183n
RTB1S1 NTB1A    0        5k
RTB1S2 NTB1A    0        5k

* Mid buffer to isolate stage 1 from stage 2
EMID NMID  0     NTA1OUT  0  1

* Stage 2
* Twin-T stage 2 — resistive arm
RTA21  NMID     NTA2A    5k
RTA22  NTA2A    NTB2OUT  5k
CTA2S1 NTA2A    0        3.183n
CTA2S2 NTA2A    0        3.183n

* Twin-T stage 2 — capacitive arm
CTB21  NMID     NTB2A    3.183n
CTB22  NTB2A    NTB2OUT  3.183n
RTB2S1 NTB2A    0        5k
RTB2S2 NTB2A    0        5k

EOUT VOUT  0     NTB2OUT  0  1
.end
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Stage 2 notch detuned | EMID missing; stage 1 output loads stage 2 | Add `EMID NMID 0 NTA1OUT 0 1`; stage 2 starts from NMID |
| Notch frequency shifted from spec | Source loading (EBUF missing) | Add `EBUF VBUF 0 VIN 0 1`; stage 1 starts from VBUF |
| VOUT is always 0 | EOUT missing | Add `EOUT VOUT 0 NTB2OUT 0 1` |
| Node name collision between stages | Stages share node names | Stage 1: NTA1A, NTB1A, NTA1OUT; Stage 2: NTA2A, NTB2A, NTB2OUT |
| Stage 2 not connected to stage 1 | Stage 2 starts from VIN or VBUF instead of NMID | Both RTA21 and CTB21 must start from NMID |
| Shallow notch | R or C mismatch | Ensure all four resistors use same R; all four caps use same C |
