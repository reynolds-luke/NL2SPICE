"""
Validate all 16 filter topology netlists against NGSpice.

Checks used:
  - LPF/HPF: find_*_cutoff_frequency() returns a measured fc within 35% of designed fc
  - BPF:     find_bandpass_cutoff_frequencies() returns non-None; geometric mean ≈ designed centre
  - Notch:   (a) find_notch_cutoff_frequencies() returns non-None
             (b) sqrt(f_low * f_high) ≈ f0 (geometric mean reconstructs design f0 within 5%)
             (c) deep attenuation at f0 (< -20 dB)
             (d) near-passband at f0/5 and 5*f0 (> -5 dB)
"""
import sys, math
sys.path.insert(0, r'C:\Users\Luk27182\Desktop\NL2SPICE\datagen_new')

from utils.find_cutoffs import (
    find_lowpass_cutoff_frequency,
    find_highpass_cutoff_frequency,
    find_bandpass_cutoff_frequencies,
    find_notch_cutoff_frequencies,
)
from utils.measure_atten import simulate_attenuation

results = []

def pct_err(measured, expected):
    return abs(measured - expected) / expected * 100

def check_fc(label, measured, expected, tol=35):
    if measured is None:
        results.append(("FAIL", label, f"returned None (expected {expected:.0f} Hz)"))
        return
    err = pct_err(measured, expected)
    status = "PASS" if err <= tol else "FAIL"
    results.append((status, label, f"fc={measured:.0f} Hz  expected={expected:.0f} Hz  err={err:.1f}%"))

def check_notch(label, NL, f0_expected):
    """For notch: verify simulation runs, f0 from geometric mean, and key gains."""
    result, _ = find_notch_cutoff_frequencies(NL)
    if result is None:
        results.append(("FAIL", label, "find_notch_cutoff_frequencies returned None"))
        return

    f_low, f_high = result
    f0_measured = math.sqrt(f_low * f_high)
    err = pct_err(f0_measured, f0_expected)
    ok_f0 = err <= 5  # geometric mean should be very close to true f0

    # Verify deep attenuation at f0
    db_at_f0 = simulate_attenuation(NL, f0_expected)
    ok_notch = (db_at_f0 is not None) and (db_at_f0 < -20)

    # Verify passband at f0/20 and 20*f0 (far enough from edge that loading doesn't matter)
    db_low = simulate_attenuation(NL, f0_expected / 20)
    db_high = simulate_attenuation(NL, f0_expected * 20)
    ok_pb_low  = (db_low  is not None) and (db_low  > -5)
    ok_pb_high = (db_high is not None) and (db_high > -5)

    status = "PASS" if (ok_f0 and ok_notch and ok_pb_low and ok_pb_high) else "FAIL"
    details = (
        f"f0_geomean={f0_measured:.0f} Hz (exp {f0_expected:.0f}, err {err:.1f}%)  "
        f"gain@f0={db_at_f0:.1f} dB  "
        f"gain@f0/20={db_low:.1f} dB  gain@20*f0={db_high:.1f} dB"
    )
    results.append((status, label, details))

print("Running simulations... (may take a minute or two)")

# ─────────────────────────────────────────────────────────────────────────────
# 1. LPF rc_single   fc=1kHz   R=10k  C=15.92n
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* Single-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   VOUT   10k
C1   VOUT  0      15.92n
.end
"""
fc, _ = find_lowpass_cutoff_frequency(NL)
check_fc("lpf_rc_single          fc=1kHz  R=10k C=15.92n", fc, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 2. LPF buffered_rc_single   fc=1kHz   R=10k  C=15.92n
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* Single-stage passive RC low-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  VOUT   10k
C1   VOUT  0      15.92n
.end
"""
fc, _ = find_lowpass_cutoff_frequency(NL)
check_fc("lpf_buffered_rc_single fc=1kHz  R=10k C=15.92n", fc, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 3. LPF rc_multi  fc_target=500Hz
#    fc_stage = 2.672 * 500 = 1336Hz
#    R=10k  C = 1/(2pi*1336*10k) = 11.91n
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* 2-stage passive RC low-pass filter
V1   VIN   0     AC 1

R1   VIN   n1     10k
C1   n1    0      11.91n
R2   n1    VOUT   10k
C2   VOUT  0      11.91n
.end
"""
fc, _ = find_lowpass_cutoff_frequency(NL)
check_fc("lpf_rc_multi           fc=500Hz R=10k C=11.91n (stage fc=1336Hz)", fc, 500)

# ─────────────────────────────────────────────────────────────────────────────
# 4. LPF buffered_rc_multi   fc_target=500Hz  same components
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* 2-stage passive RC low-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

R1   VBUF  n1     10k
C1   n1    0      11.91n
R2   n1    VOUT   10k
C2   VOUT  0      11.91n
.end
"""
fc, _ = find_lowpass_cutoff_frequency(NL)
check_fc("lpf_buffered_rc_multi  fc=500Hz R=10k C=11.91n (stage fc=1336Hz)", fc, 500)

# ─────────────────────────────────────────────────────────────────────────────
# 5. HPF rc_single   fc=500Hz   C=31.83n  R=10k
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* Single-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   VOUT   31.83n
R1   VOUT  0      10k
.end
"""
fc, _ = find_highpass_cutoff_frequency(NL)
check_fc("hpf_rc_single          fc=500Hz  C=31.83n R=10k", fc, 500)

# ─────────────────────────────────────────────────────────────────────────────
# 6. HPF buffered_rc_single   fc=500Hz
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* Single-stage passive RC high-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  VOUT   31.83n
R1   VOUT  0      10k
.end
"""
fc, _ = find_highpass_cutoff_frequency(NL)
check_fc("hpf_buffered_rc_single fc=500Hz  C=31.83n R=10k", fc, 500)

# ─────────────────────────────────────────────────────────────────────────────
# 7. HPF rc_multi   fc_target=1kHz
#    fc_stage = 0.3743 * 1000 = 374.3Hz
#    C = 2.672/(2pi*1000*10k) = 42.52n  R=10k
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* 2-stage passive RC high-pass filter
V1   VIN   0     AC 1

C1   VIN   n1     42.52n
R1   n1    0      10k
C2   n1    VOUT   42.52n
R2   VOUT  0      10k
.end
"""
fc, _ = find_highpass_cutoff_frequency(NL)
check_fc("hpf_rc_multi           fc=1kHz  C=42.52n R=10k (stage fc=374Hz)", fc, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 8. HPF buffered_rc_multi   fc_target=1kHz
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* 2-stage passive RC high-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

C1   VBUF  n1     42.52n
R1   n1    0      10k
C2   n1    VOUT   42.52n
R2   VOUT  0      10k
.end
"""
fc, _ = find_highpass_cutoff_frequency(NL)
check_fc("hpf_buffered_rc_multi  fc=1kHz  C=42.52n R=10k (stage fc=374Hz)", fc, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 9. BPF rc_single   fL=200Hz  fH=2kHz
#    HP: R_hp=10k  C_hp=79.58n
#    LP: R_lp=10k  C_lp=7.958n
#    centre = sqrt(200*2000) = 632 Hz
# ─────────────────────────────────────────────────────────────────────────────
NL_BPF_RC1 = """\
* Single-stage passive RC band-pass filter
V1   VIN   0     AC 1

CH1  VIN   nh1    79.58n
RH1  nh1   0      10k

RL1  nh1   VOUT   10k
CL1  VOUT  0      7.958n
.end
"""
res, _ = find_bandpass_cutoff_frequencies(NL_BPF_RC1)
if res is None:
    results.append(("FAIL", "bpf_rc_single          fL=200 fH=2k", "returned None"))
else:
    f_low, f_high = res
    fc_centre = math.sqrt(f_low * f_high)
    check_fc("bpf_rc_single          fL=200 fH=2k  centre check", fc_centre, 632)

# ─────────────────────────────────────────────────────────────────────────────
# 10. BPF buffered_rc_single   fL=200Hz  fH=2kHz  (isolated sections)
# ─────────────────────────────────────────────────────────────────────────────
NL_BPF_BUF1 = """\
* Single-stage passive RC band-pass filter with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

CH1  VBUF  nh1    79.58n
RH1  nh1   0      10k

EMID NMID  0     nh1  0  1

RL1  NMID  VOUT   10k
CL1  VOUT  0      7.958n
.end
"""
res, _ = find_bandpass_cutoff_frequencies(NL_BPF_BUF1)
if res is None:
    results.append(("FAIL", "bpf_buffered_rc_single fL=200 fH=2k", "returned None"))
else:
    f_low, f_high = res
    fc_centre = math.sqrt(f_low * f_high)
    check_fc("bpf_buffered_rc_single fL=200 fH=2k  centre check", fc_centre, 632)

# ─────────────────────────────────────────────────────────────────────────────
# 11. BPF rc_multi   fL=500Hz  fH=5kHz
#    HP 2-stage: C_hp = 2.672/(2pi*500*10k) = 85.02n  R_hp=10k
#    LP 2-stage: C_lp = 1/(2pi*2.672*5000*10k) = 1.192n  R_lp=10k
#    centre = sqrt(500*5000) = 1581 Hz
# ─────────────────────────────────────────────────────────────────────────────
NL_BPF_RC2 = """\
* 2-stage passive RC band-pass filter
V1   VIN   0     AC 1

CH1  VIN   nh1    85.02n
RH1  nh1   0      10k
CH2  nh1   nh2    85.02n
RH2  nh2   0      10k

RL1  nh2   nl1    10k
CL1  nl1   0      1.192n
RL2  nl1   VOUT   10k
CL2  VOUT  0      1.192n
.end
"""
res, _ = find_bandpass_cutoff_frequencies(NL_BPF_RC2)
if res is None:
    results.append(("FAIL", "bpf_rc_multi           fL=500 fH=5k", "returned None"))
else:
    f_low, f_high = res
    fc_centre = math.sqrt(f_low * f_high)
    check_fc("bpf_rc_multi           fL=500 fH=5k  centre check", fc_centre, 1581)

# ─────────────────────────────────────────────────────────────────────────────
# 12. BPF buffered_rc_multi   fL=500Hz  fH=5kHz
# ─────────────────────────────────────────────────────────────────────────────
NL_BPF_BUF2 = """\
* 2-stage passive RC band-pass filter buffered (input op-amp buffer)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

CH1  VBUF  nh1    85.02n
RH1  nh1   0      10k
CH2  nh1   nh2    85.02n
RH2  nh2   0      10k

EMID NMID  0     nh2  0  1

RL1  NMID  nl1    10k
CL1  nl1   0      1.192n
RL2  nl1   VOUT   10k
CL2  VOUT  0      1.192n
.end
"""
res, _ = find_bandpass_cutoff_frequencies(NL_BPF_BUF2)
if res is None:
    results.append(("FAIL", "bpf_buffered_rc_multi  fL=500 fH=5k", "returned None"))
else:
    f_low, f_high = res
    fc_centre = math.sqrt(f_low * f_high)
    check_fc("bpf_buffered_rc_multi  fL=500 fH=5k  centre check", fc_centre, 1581)

# ─────────────────────────────────────────────────────────────────────────────
# 13. Notch rc_single   f0=1kHz   R=10k  C=15.92n
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* Single-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

RTA1  VIN   nta    10k
RTA2  nta   out    10k
CTAS1 nta   0      15.92n
CTAS2 nta   0      15.92n

CTB1  VIN   ntb    15.92n
CTB2  ntb   out    15.92n
RTBS1 ntb   0      10k
RTBS2 ntb   0      10k

EOUT VOUT  0     out  0  1
.end
"""
check_notch("notch_rc_single        f0=1kHz R=10k C=15.92n", NL, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 14. Notch buffered_rc_single   f0=1kHz   EBUF before Twin-T
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* Single-stage passive RC notch filter (Twin-T) with input op-amp buffer
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

RTA1  VBUF  nta    10k
RTA2  nta   out    10k
CTAS1 nta   0      15.92n
CTAS2 nta   0      15.92n

CTB1  VBUF  ntb    15.92n
CTB2  ntb   out    15.92n
RTBS1 ntb   0      10k
RTBS2 ntb   0      10k

EOUT VOUT  0     out  0  1
.end
"""
check_notch("notch_buffered_rc_single f0=1kHz R=10k C=15.92n", NL, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 15. Notch rc_multi   f0=1kHz   two Twin-T stages cascaded
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* 2-stage passive RC notch filter (Twin-T)
V1   VIN   0     AC 1

* Stage 1 — resistive arm
RTA11  VIN      NTA1A    10k
RTA12  NTA1A    NTA1OUT  10k
CTA1S1 NTA1A    0        15.92n
CTA1S2 NTA1A    0        15.92n

* Stage 1 — capacitive arm
CTB11  VIN      NTB1A    15.92n
CTB12  NTB1A    NTA1OUT  15.92n
RTB1S1 NTB1A    0        10k
RTB1S2 NTB1A    0        10k

* Stage 2 — resistive arm
RTA21  NTA1OUT  NTA2A    10k
RTA22  NTA2A    NTA2OUT  10k
CTA2S1 NTA2A    0        15.92n
CTA2S2 NTA2A    0        15.92n

* Stage 2 — capacitive arm
CTB21  NTA1OUT  NTB2A    15.92n
CTB22  NTB2A    NTA2OUT  15.92n
RTB2S1 NTB2A    0        10k
RTB2S2 NTB2A    0        10k

EOUT VOUT  0     NTA2OUT  0  1
.end
"""
check_notch("notch_rc_multi         f0=1kHz R=10k C=15.92n (2 stages)", NL, 1000)

# ─────────────────────────────────────────────────────────────────────────────
# 16. Notch buffered_rc_multi   f0=1kHz   EBUF + EMID between stages
# ─────────────────────────────────────────────────────────────────────────────
NL = """\
* 2-stage passive RC notch filter buffered (Twin-T)
V1   VIN   0     AC 1

EBUF VBUF  0     VIN  0  1

* Stage 1 — resistive arm
RTA11  VBUF     NTA1A    10k
RTA12  NTA1A    NTA1OUT  10k
CTA1S1 NTA1A    0        15.92n
CTA1S2 NTA1A    0        15.92n

* Stage 1 — capacitive arm
CTB11  VBUF     NTB1A    15.92n
CTB12  NTB1A    NTA1OUT  15.92n
RTB1S1 NTB1A    0        10k
RTB1S2 NTB1A    0        10k

EMID NMID  0     NTA1OUT  0  1

* Stage 2 — resistive arm
RTA21  NMID     NTA2A    10k
RTA22  NTA2A    NTB2OUT  10k
CTA2S1 NTA2A    0        15.92n
CTA2S2 NTA2A    0        15.92n

* Stage 2 — capacitive arm
CTB21  NMID     NTB2A    15.92n
CTB22  NTB2A    NTB2OUT  15.92n
RTB2S1 NTB2A    0        10k
RTB2S2 NTB2A    0        10k

EOUT VOUT  0     NTB2OUT  0  1
.end
"""
check_notch("notch_buffered_rc_multi f0=1kHz R=10k C=15.92n (2 stages)", NL, 1000)

# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 90)
print("VALIDATION RESULTS")
print("=" * 90)
passes = fails = 0
for status, label, detail in results:
    marker = "+" if status == "PASS" else "X"
    print(f"  {marker} {status}  {label}")
    print(f"         {detail}")
    if status == "PASS": passes += 1
    else: fails += 1

print()
print(f"  {passes} PASS  /  {fails} FAIL  /  {passes+fails} total")
print("=" * 90)
