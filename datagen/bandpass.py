"""
bpf_prompt_generator.py
=======================
Generates natural-language design prompts for band-pass filter circuits.
Each prompt uniquely specifies the required performance without naming
the topology, so it can be used to evaluate an LLM's circuit design ability.

Topologies covered
------------------
  single      - one HP stage + one LP stage, both passive RC
  multi       - cascaded passive RC stages on one or both skirts
  buf         - single HP + single LP stage, one op-amp buffer
  bufmulti    - multi-stage on one or both skirts, one op-amp buffer

Topology selection rules (deterministic given sampled params)
-------------------------------------------------------------
  buffered  = high_z_source OR low_z_load
  multi     = n_stages_low > 1  OR  n_stages_high > 1
  ->  single    : not buffered, not multi
  ->  multi     : not buffered, multi
  ->  buf       : buffered, not multi
  ->  bufmulti  : buffered, multi

Parameter sampling order (guarantees physical consistency)
----------------------------------------------------------
  1. Sample rolloff_low_dbpdec  independently from valid sets.
     Sample rolloff_high_dbpdec independently from valid sets.
       single/buf skirts : 20 dB/decade each
       multi/bufmulti    : at least one skirt from {40, 60, 80, 100}
  2. Sample fc_low  (log-uniform).
     Sample bw_ratio -> fc_high = fc_low * bw_ratio   (fc_high > fc_low).
  3. Sample fs_low_ratio  -> fs_low  = fc_low  / fs_low_ratio   (fs_low  < fc_low).
     Sample fs_high_ratio -> fs_high = fc_high * fs_high_ratio  (fs_high > fc_high).
     Both fs values are rounded to 1 significant figure.
  4. Derive:
       atten_low_db  = rolloff_low_dbpdec  * log10(fc_low  / fs_low)
       atten_high_db = rolloff_high_dbpdec * log10(fs_high / fc_high)
     Both are always physically achievable by construction.

SPICE node convention (enforced in every prompt via the post-amble)
-------------------------------------------------------------------
  VIN   - input node
  VOUT  - output node
  GND   - ground / reference node (0 V)
"""

import random
import math
import json
from dataclasses import dataclass, asdict
from typing import Optional


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

ROLLOFF_SINGLE_DBPDEC: float = 20.0
ROLLOFF_MULTI_OPTIONS: list[float] = [40.0, 60.0, 80.0, 100.0]  # 2–5 stages

# Lower corner frequency range (Hz) — sampled on log scale.
# fc_high is derived from fc_low * bw_ratio, so the upper end is kept modest
# to prevent fc_high from exceeding a sensible ceiling.
FC_LOW_LOG_RANGE = (100, 20_000)

# Passband width ratio: fc_high = fc_low * bw_ratio
BW_RATIO_OPTIONS = [2, 3, 4, 5, 10]

# Stopband frequency ratio (outward from each corner):
#   fs_low  = fc_low  / fs_low_ratio
#   fs_high = fc_high * fs_high_ratio
FS_RATIO_OPTIONS = [2, 3, 4, 5, 10]

# Passband ripple options (dB)
PB_LOSS_OPTIONS = [0.5, 1.0, 1.0, 1.0, 2.0, 3.0]   # weighted towards 1 dB

# Load impedances used in low-Z scenarios
LOW_Z_LOAD_OPTIONS = [500, 1_000, 1_500, 2_000, 4_700]


# -----------------------------------------------------------------------------
# Parameter dataclass
# -----------------------------------------------------------------------------

@dataclass
class BPFParams:
    topology: str                   # 'single' | 'multi' | 'buf' | 'bufmulti'
    fc_low_hz: float                # lower -3 dB corner frequency
    fc_high_hz: float               # upper -3 dB corner frequency
    bw_ratio: float                 # fc_high_hz / fc_low_hz
    fs_low_hz: float                # lower stopband frequency  (fs_low < fc_low)
    fs_high_hz: float               # upper stopband frequency  (fs_high > fc_high)
    fs_low_ratio: float             # fc_low_hz / fs_low_hz
    fs_high_ratio: float            # fs_high_hz / fc_high_hz
    pb_loss_db: float               # max passband insertion loss (dB)
    rolloff_low_dbpdec: float       # rolloff rate on the lower (HPF) skirt
    rolloff_high_dbpdec: float      # rolloff rate on the upper (LPF) skirt
    atten_low_db: float             # derived lower stopband attenuation (dB)
    atten_high_db: float            # derived upper stopband attenuation (dB)
    n_stages_low: int               # HP RC stages on lower skirt
    n_stages_high: int              # LP RC stages on upper skirt
    high_z_source: bool
    low_z_load: bool
    load_r_ohm: Optional[int]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _log_sample_hz(lo: float, hi: float) -> float:
    """Sample a frequency on a log scale, then round to 1 significant figure."""
    v = 10 ** random.uniform(math.log10(lo), math.log10(hi))
    mag = 10 ** math.floor(math.log10(v))
    return round(v / mag) * mag


def _round_1sf(v: float) -> float:
    """Round a positive value to 1 significant figure."""
    mag = 10 ** math.floor(math.log10(v))
    return round(v / mag) * mag


def _atten(rolloff_dbpdec: float, f_corner: float, f_stop: float) -> float:
    """
    Attenuation at f_stop for a filter whose corner is f_corner and whose
    rolloff rate is rolloff_dbpdec.  Works for both skirts:
      lower skirt : f_corner = fc_low,  f_stop = fs_low  (fc > fs, ratio > 1)
      upper skirt : f_corner = fc_high, f_stop = fs_high (fs > fc, ratio > 1)
    In both cases the ratio passed here is > 1 so log10 is positive.
    """
    ratio = max(f_corner, f_stop) / min(f_corner, f_stop)
    return round(rolloff_dbpdec * math.log10(ratio), 1)


# -----------------------------------------------------------------------------
# Sampler
# -----------------------------------------------------------------------------

def sample_params(
    force_high_z: Optional[bool] = None,
    force_low_z:  Optional[bool] = None,
    force_multi:  Optional[bool] = None,
) -> BPFParams:
    """
    Sample a random-but-valid set of BPF design parameters.

    Sampling order
    --------------
    1. Decide buffering (high_z / low_z).
    2. Decide whether multi-stage is required (force_multi or random).
    3. Sample rolloff rates for each skirt from the appropriate sets.
       For 'multi', at least one skirt must be multi-stage; the other is
       randomly single or multi.
    4. Sample fc_low (log-uniform) and bw_ratio -> fc_high.
    5. Sample fs_low_ratio  -> fs_low  = fc_low  / fs_low_ratio  (rounded).
       Sample fs_high_ratio -> fs_high = fc_high * fs_high_ratio (rounded).
    6. Derive atten_low_db and atten_high_db.
    7. Derive n_stages_low and n_stages_high.
    8. Assign topology label.
    """
    # --- Step 1: buffering ---------------------------------------------------
    high_z = force_high_z if force_high_z is not None else (random.random() < 0.4)
    low_z  = force_low_z  if force_low_z  is not None else (random.random() < 0.35)
    buffered = high_z or low_z

    # --- Step 2: multi-stage decision ----------------------------------------
    multi = force_multi if force_multi is not None else (random.random() < 0.5)

    # --- Step 3: rolloff rates -----------------------------------------------
    if multi:
        # Guarantee at least one multi-stage skirt; let the other vary freely.
        guaranteed_skirt = random.choice(["low", "high"])
        if guaranteed_skirt == "low":
            rolloff_low  = random.choice(ROLLOFF_MULTI_OPTIONS)
            rolloff_high = random.choice([ROLLOFF_SINGLE_DBPDEC] + ROLLOFF_MULTI_OPTIONS)
        else:
            rolloff_low  = random.choice([ROLLOFF_SINGLE_DBPDEC] + ROLLOFF_MULTI_OPTIONS)
            rolloff_high = random.choice(ROLLOFF_MULTI_OPTIONS)
    else:
        rolloff_low  = ROLLOFF_SINGLE_DBPDEC
        rolloff_high = ROLLOFF_SINGLE_DBPDEC

    n_stages_low  = int(round(rolloff_low  / 20.0))
    n_stages_high = int(round(rolloff_high / 20.0))

    # --- Step 4: passband frequencies ----------------------------------------
    fc_low_hz  = _log_sample_hz(*FC_LOW_LOG_RANGE)
    bw_ratio   = random.choice(BW_RATIO_OPTIONS)
    fc_high_hz = _round_1sf(fc_low_hz * bw_ratio)

    # --- Step 5: stopband frequencies ----------------------------------------
    fs_low_ratio  = random.choice(FS_RATIO_OPTIONS)
    fs_high_ratio = random.choice(FS_RATIO_OPTIONS)

    fs_low_hz  = _round_1sf(fc_low_hz  / fs_low_ratio)   # below lower corner
    fs_high_hz = _round_1sf(fc_high_hz * fs_high_ratio)  # above upper corner

    # --- Step 6: derived attenuations ----------------------------------------
    atten_low_db  = _atten(rolloff_low,  fc_low_hz,  fs_low_hz)
    atten_high_db = _atten(rolloff_high, fc_high_hz, fs_high_hz)

    # --- Step 7: passband loss -----------------------------------------------
    pb_loss = random.choice(PB_LOSS_OPTIONS)

    # --- Step 8: load impedance ----------------------------------------------
    load_r = random.choice(LOW_Z_LOAD_OPTIONS) if (buffered and low_z) else None

    # --- Step 9: topology label ----------------------------------------------
    if not buffered and not multi:
        topo = "single"
    elif not buffered and multi:
        topo = "multi"
    elif buffered and not multi:
        topo = "buf"
    else:
        topo = "bufmulti"

    return BPFParams(
        topology=topo,
        fc_low_hz=fc_low_hz,
        fc_high_hz=fc_high_hz,
        bw_ratio=bw_ratio,
        fs_low_hz=fs_low_hz,
        fs_high_hz=fs_high_hz,
        fs_low_ratio=fs_low_ratio,
        fs_high_ratio=fs_high_ratio,
        pb_loss_db=pb_loss,
        rolloff_low_dbpdec=rolloff_low,
        rolloff_high_dbpdec=rolloff_high,
        atten_low_db=atten_low_db,
        atten_high_db=atten_high_db,
        n_stages_low=n_stages_low,
        n_stages_high=n_stages_high,
        high_z_source=high_z,
        low_z_load=low_z and buffered,
        load_r_ohm=load_r,
    )


# -----------------------------------------------------------------------------
# Frequency formatter
# -----------------------------------------------------------------------------

def _fmt_hz(f: float) -> str:
    if f >= 1_000:
        v = f / 1_000
        return f"{v:g} kHz"
    return f"{f:g} Hz"


# -----------------------------------------------------------------------------
# Template banks  (10 variants per topology)
# -----------------------------------------------------------------------------
#
# Placeholders:
#   {fc_low}      - lower passband edge (formatted)
#   {fc_high}     - upper passband edge (formatted)
#   {fs_low}      - lower stopband frequency (formatted)   fs_low  < fc_low
#   {fs_high}     - upper stopband frequency (formatted)   fs_high > fc_high
#   {pb}          - passband insertion loss limit (dB)
#   {atten_low}   - lower stopband attenuation (dB)
#   {atten_high}  - upper stopband attenuation (dB)
#   {load_r}      - load resistance in ohm (with-load banks only)
#
# Templates deliberately do NOT name the topology.
# -----------------------------------------------------------------------------

TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage (one HP + one LP RC, purely passive) --------------------
    "single": [
        # 1
        "Design a band-pass filter to isolate a signal of interest from broadband noise. "
        "The passband must extend from {fc_low} to {fc_high} with no more than {pb} dB of insertion loss. "
        "Low-frequency content at {fs_low} must be attenuated by at least {atten_low} dB. "
        "High-frequency content at {fs_high} must be attenuated by at least {atten_high} dB. "
        "Use only resistors and capacitors; minimise component count.",

        # 2
        "Create a simple band-pass filter for a low-impedance signal source. "
        "Signals between {fc_low} and {fc_high} must pass with less than {pb} dB loss. "
        "Rejection at {fs_low} must be at least {atten_low} dB; "
        "rejection at {fs_high} must be at least {atten_high} dB. "
        "No active components are permitted; optimise for minimum cost.",

        # 3
        "Specify a passive RC band-pass network for a signal conditioning application. "
        "The passband extends from {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "The filter must attenuate {fs_low} by >= {atten_low} dB and {fs_high} by >= {atten_high} dB. "
        "Use only resistors and capacitors; keep the design as simple as possible.",

        # 4
        "A band-pass filter is needed to select a specific frequency band before an ADC input. "
        "Signals from {fc_low} to {fc_high} must experience no more than {pb} dB of loss. "
        "Out-of-band interference at {fs_low} must be suppressed by at least {atten_low} dB. "
        "Out-of-band interference at {fs_high} must be suppressed by at least {atten_high} dB. "
        "Permitted components: resistors and capacitors only.",

        # 5
        "Design a band-pass filter for a standard-impedance signal path. "
        "Pass signals between {fc_low} and {fc_high} with under {pb} dB loss. "
        "Provide at least {atten_low} dB of attenuation at {fs_low} "
        "and at least {atten_high} dB of attenuation at {fs_high}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a band-pass network to extract a narrowband signal from a wideband input. "
        "The passband must run from {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "Signals at {fs_low} must be reduced by at least {atten_low} dB. "
        "Signals at {fs_high} must be reduced by at least {atten_high} dB. "
        "Restrict to resistors and capacitors; use as few components as possible.",

        # 7
        "A passive band-pass filter is required for a data acquisition front end. "
        "Signals between {fc_low} and {fc_high} should experience at most {pb} dB of loss. "
        "Signals at {fs_low} must be attenuated by no less than {atten_low} dB. "
        "Signals at {fs_high} must be attenuated by no less than {atten_high} dB. "
        "Use only R and C components; minimise cost.",

        # 8
        "Design a band-pass filter to select a frequency band before sampling. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "A minimum of {atten_low} dB rejection is required at {fs_low}. "
        "A minimum of {atten_high} dB rejection is required at {fs_high}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A band-pass pre-filter is required to reduce out-of-band interference before a receiver stage. "
        "It must pass signals between {fc_low} and {fc_high} with less than {pb} dB attenuation "
        "while rejecting {fs_low} by at least {atten_low} dB and {fs_high} by at least {atten_high} dB. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a passive band-pass filter design for a general-purpose frequency selection application. "
        "The -{pb} dB frequencies should fall at or outside {fc_low} and {fc_high}. "
        "At {fs_low} the filter must deliver >= {atten_low} dB of attenuation. "
        "At {fs_high} the filter must deliver >= {atten_high} dB of attenuation. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage RC (steeper skirts, passive) ------------------------------
    "multi": [
        # 1
        "Design a band-pass filter with steep skirts for a signal conditioning application. "
        "The passband must extend from {fc_low} to {fc_high} with no more than {pb} dB of insertion loss. "
        "Low-frequency interference at {fs_low} must be attenuated by at least {atten_low} dB. "
        "High-frequency interference at {fs_high} must be attenuated by at least {atten_high} dB. "
        "Use only resistors and capacitors; minimise total component count.",

        # 2
        "Create a high-selectivity passive band-pass filter for a measurement system. "
        "Signals from {fc_low} to {fc_high} must pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten_low} dB of rejection at {fs_low} "
        "and at least {atten_high} dB of rejection at {fs_high}. "
        "No active components; keep the design as cost-effective as possible.",

        # 3
        "Specify a passive RC band-pass filter with demanding out-of-band rejection. "
        "The passband edges are {fc_low} and {fc_high} with <= {pb} dB loss. "
        "A minimum of {atten_low} dB attenuation is required at {fs_low}. "
        "A minimum of {atten_high} dB attenuation is required at {fs_high}. "
        "Use only resistors and capacitors; use the fewest stages that meet the spec.",

        # 4
        "Design a passive band-pass filter to provide aggressive out-of-band noise rejection. "
        "Pass signals between {fc_low} and {fc_high} with under {pb} dB loss. "
        "At {fs_low}, the attenuation must be at least {atten_low} dB. "
        "At {fs_high}, the attenuation must be at least {atten_high} dB. "
        "Permitted components: resistors and capacitors only. Optimise for minimum cost.",

        # 5
        "A signal must be tightly band-pass filtered before entering a sensitive measurement circuit. "
        "The passband runs from {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "At least {atten_low} dB of suppression is needed at {fs_low}. "
        "At least {atten_high} dB of suppression is needed at {fs_high}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a band-pass filter with sharp skirts for an EMC pre-compliance measurement. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB attenuation. "
        "Out-of-band signals at {fs_low} must be reduced by a minimum of {atten_low} dB. "
        "Out-of-band signals at {fs_high} must be reduced by a minimum of {atten_high} dB. "
        "Use only resistors and capacitors; favour the simplest topology that meets these figures.",

        # 7
        "A passive band-pass network is required to achieve high out-of-band attenuation. "
        "The insertion loss must be below {pb} dB throughout the passband from {fc_low} to {fc_high}. "
        "The circuit must achieve >= {atten_low} dB attenuation at {fs_low} "
        "and >= {atten_high} dB attenuation at {fs_high}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive band-pass filter for a data acquisition front end requiring strong out-of-band rejection. "
        "Signals between {fc_low} and {fc_high} must pass with less than {pb} dB loss. "
        "Signals at {fs_low} must be suppressed by at least {atten_low} dB. "
        "Signals at {fs_high} must be suppressed by at least {atten_high} dB. "
        "Only R and C components; favour the lowest-cost design that meets all requirements.",

        # 9
        "Provide a band-pass filter design with high out-of-band rejection using only passive components. "
        "The passband spans {fc_low} to {fc_high} with a maximum of {pb} dB insertion loss. "
        "At {fs_low}, a minimum of {atten_low} dB attenuation is required. "
        "At {fs_high}, a minimum of {atten_high} dB attenuation is required. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A band-pass filter is needed with demanding stopband specifications on both skirts. "
        "Frequencies between {fc_low} and {fc_high} must be passed with <= {pb} dB loss. "
        "At {fs_low} the filter must attenuate signals by at least {atten_low} dB. "
        "At {fs_high} the filter must attenuate signals by at least {atten_high} dB. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single-stage: high-Z source, no load constraint -------------
    "buf_no_load": [
        # 1
        "Design a band-pass filter for a high-impedance signal source. "
        "The passband must extend from {fc_low} to {fc_high} with no more than {pb} dB of insertion loss. "
        "At {fs_low}, at least {atten_low} dB of attenuation is required. "
        "At {fs_high}, at least {atten_high} dB of attenuation is required. "
        "Use resistors, capacitors, and at most one op-amp if needed for impedance buffering. "
        "Keep the circuit as simple and inexpensive as possible.",

        # 2
        "A signal from a high-impedance source must be band-pass filtered before further processing. "
        "The filter should pass frequencies from {fc_low} to {fc_high} with <= {pb} dB attenuation. "
        "Rejection at {fs_low} must be at least {atten_low} dB; "
        "rejection at {fs_high} must be at least {atten_high} dB. "
        "Use passive R and C components; add one op-amp only where required by the impedance constraints.",

        # 3
        "A measurement system has a high-impedance signal source that cannot drive loads directly. "
        "A band-pass filter is required that passes {fc_low} to {fc_high} with <= {pb} dB loss, "
        "attenuates {fs_low} by at least {atten_low} dB, and attenuates {fs_high} by at least {atten_high} dB. "
        "Use one op-amp if required; otherwise use only resistors and capacitors.",

        # 4
        "Build a band-pass filter that can accept a signal from a high-impedance source. "
        "Frequencies from {fc_low} to {fc_high} must pass with no more than {pb} dB attenuation. "
        "Frequencies at {fs_low} must be reduced by at least {atten_low} dB. "
        "Frequencies at {fs_high} must be reduced by at least {atten_high} dB. "
        "Use resistors, capacitors, and optionally one op-amp; minimise component count.",

        # 5
        "Design a band-pass filter for a high-impedance source requiring impedance buffering. "
        "The filter must pass signals from {fc_low} to {fc_high} with <= {pb} dB insertion loss, "
        "attenuate {fs_low} by at least {atten_low} dB, and attenuate {fs_high} by at least {atten_high} dB. "
        "Use resistors and capacitors; one op-amp is allowed if necessary for correct operation.",

        # 6
        "Create a band-pass filter to condition a weak signal from a high-impedance transducer. "
        "Signals between {fc_low} and {fc_high} must pass with less than {pb} dB loss. "
        "Out-of-band interference at {fs_low} must be suppressed by at least {atten_low} dB. "
        "Out-of-band interference at {fs_high} must be suppressed by at least {atten_high} dB. "
        "Permitted components: resistors, capacitors, and at most one op-amp. Minimise cost.",

        # 7
        "Specify a band-pass filter for a high-impedance sensor output. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "Stopband attenuation at {fs_low} must reach at least {atten_low} dB. "
        "Stopband attenuation at {fs_high} must reach at least {atten_high} dB. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 8
        "A high-impedance transducer output needs band-pass filtering before digitisation. "
        "The passband must run from {fc_low} to {fc_high} with under {pb} dB insertion loss. "
        "At {fs_low}, the circuit must deliver at least {atten_low} dB of rejection. "
        "At {fs_high}, the circuit must deliver at least {atten_high} dB of rejection. "
        "Allow one op-amp alongside passive R and C; keep the design as simple as possible.",

        # 9
        "Provide a band-pass filter design for a high-impedance signal source. "
        "The insertion loss must be below {pb} dB between {fc_low} and {fc_high}. "
        "A minimum of {atten_low} dB attenuation is required at {fs_low}. "
        "A minimum of {atten_high} dB attenuation is required at {fs_high}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 10
        "Design a band-pass filter for a sensor with high output impedance. "
        "Signals between {fc_low} and {fc_high} must be passed with <= {pb} dB loss. "
        "Signals at {fs_low} must be attenuated by at least {atten_low} dB. "
        "Signals at {fs_high} must be attenuated by at least {atten_high} dB. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum part count.",
    ],

    # -- Buffered single-stage: high-Z source + explicit low-Z load -----------
    "buf_with_load": [
        # 1
        "Create a band-pass filter to condition a weak signal from a high-impedance transducer "
        "and drive a {load_r} ohm load. "
        "Signals from {fc_low} to {fc_high} must pass with less than {pb} dB loss. "
        "Interference at {fs_low} must be suppressed by at least {atten_low} dB. "
        "Interference at {fs_high} must be suppressed by at least {atten_high} dB. "
        "Permitted components: resistors, capacitors, and at most one op-amp.",

        # 2
        "Specify a band-pass filter for a high-impedance sensor output feeding a {load_r} ohm load. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "Stopband attenuation at {fs_low} must reach at least {atten_low} dB. "
        "Stopband attenuation at {fs_high} must reach at least {atten_high} dB. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 3
        "Design a band-pass filter to interface a high-impedance source to a {load_r} ohm downstream circuit. "
        "Pass signals from {fc_low} to {fc_high} with under {pb} dB insertion loss. "
        "Provide >= {atten_low} dB of rejection at {fs_low} and >= {atten_high} dB of rejection at {fs_high}. "
        "Components are limited to resistors, capacitors, and one op-amp if needed. Minimise cost.",

        # 4
        "Design a band-pass filter for a sensor interface where the source impedance is high "
        "and the load is {load_r} ohm. "
        "The passband must span {fc_low} to {fc_high} with less than {pb} dB loss. "
        "At {fs_low}, at least {atten_low} dB of suppression is needed. "
        "At {fs_high}, at least {atten_high} dB of suppression is needed. "
        "Allow resistors, capacitors, and at most one op-amp; keep the design simple.",

        # 5
        "Provide a band-pass filter design for a high-impedance signal source driving a {load_r} ohm load. "
        "The insertion loss must be below {pb} dB from {fc_low} to {fc_high}. "
        "A minimum of {atten_low} dB attenuation is required at {fs_low}. "
        "A minimum of {atten_high} dB attenuation is required at {fs_high}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 6
        "A high-impedance sensor feeds a {load_r} ohm input stage. "
        "Design a band-pass filter between them that passes {fc_low} to {fc_high} with <= {pb} dB loss, "
        "rejects {fs_low} by at least {atten_low} dB, and rejects {fs_high} by at least {atten_high} dB. "
        "Use resistors, capacitors, and one op-amp if necessary; minimise component count.",

        # 7
        "Design a band-pass filter for a high-impedance signal source driving a {load_r} ohm load. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "At {fs_low}, at least {atten_low} dB of rejection is required. "
        "At {fs_high}, at least {atten_high} dB of rejection is required. "
        "Use R, C, and at most one op-amp; optimise for low cost.",

        # 8
        "A weak, high-impedance signal must be band-pass filtered and presented to a {load_r} ohm load. "
        "The filter must pass {fc_low} to {fc_high} with less than {pb} dB loss, "
        "suppress {fs_low} by at least {atten_low} dB, and suppress {fs_high} by at least {atten_high} dB. "
        "Allow one op-amp if needed; otherwise restrict to passive components.",

        # 9
        "Specify a band-pass filter to buffer a high-impedance source and drive a {load_r} ohm load. "
        "Signals from {fc_low} to {fc_high} must be passed with <= {pb} dB attenuation. "
        "At {fs_low}, the attenuation must be at least {atten_low} dB. "
        "At {fs_high}, the attenuation must be at least {atten_high} dB. "
        "Use resistors, capacitors, and optionally one op-amp; favour the simplest design.",

        # 10
        "Build a band-pass filter for a high-impedance sensor output connected to a {load_r} ohm input. "
        "The circuit must pass {fc_low} to {fc_high} with under {pb} dB insertion loss, "
        "deliver >= {atten_low} dB rejection at {fs_low}, and deliver >= {atten_high} dB rejection at {fs_high}. "
        "Permitted parts: R, C, and one op-amp if required. Keep BOM cost minimal.",
    ],

    # -- Buffered multi-stage: high-Z source, no load constraint --------------
    "bufmulti_no_load": [
        # 1
        "Design a band-pass filter for a high-impedance signal source requiring high out-of-band attenuation. "
        "The passband must reach from {fc_low} to {fc_high} with no more than {pb} dB insertion loss. "
        "At {fs_low}, at least {atten_low} dB of attenuation is required. "
        "At {fs_high}, at least {atten_high} dB of attenuation is required. "
        "Use resistors, capacitors, and at most one op-amp. Minimise cost and component count.",

        # 2
        "A high-impedance transducer feeds a band-pass filter that must deliver strong out-of-band rejection. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB attenuation. "
        "The attenuation at {fs_low} must be >= {atten_low} dB. "
        "The attenuation at {fs_high} must be >= {atten_high} dB. "
        "Use resistors, capacitors, and at most one op-amp; use the fewest stages that meet the specification.",

        # 3
        "Design a band-pass filter with aggressive out-of-band rejection for a high-impedance sensor interface. "
        "The passband must span {fc_low} to {fc_high} with under {pb} dB loss. "
        "Provide >= {atten_low} dB of rejection at {fs_low} and >= {atten_high} dB of rejection at {fs_high}. "
        "An op-amp is permitted to handle source impedance; use only passive components otherwise.",

        # 4
        "Design a band-pass filter for a high-impedance signal source with demanding stopband requirements. "
        "Frequencies from {fc_low} to {fc_high} must be passed with less than {pb} dB loss. "
        "At {fs_low}, the filter must deliver at least {atten_low} dB of attenuation. "
        "At {fs_high}, the filter must deliver at least {atten_high} dB of attenuation. "
        "Restrict components to resistors, capacitors, and at most one op-amp; minimise part count.",

        # 5
        "Provide a band-pass filter design for a high-impedance source requiring both "
        "impedance buffering and steep skirt roll-off. "
        "The insertion loss must be below {pb} dB throughout the passband from {fc_low} to {fc_high}. "
        "At {fs_low}, at least {atten_low} dB of attenuation is required. "
        "At {fs_high}, at least {atten_high} dB of attenuation is required. "
        "Use resistors, capacitors, and one op-amp; minimise the total number of components.",

        # 6
        "A high-impedance sensor signal requires heavy band-pass filtering before digitisation. "
        "Signals from {fc_low} to {fc_high} must pass with <= {pb} dB loss. "
        "Signals at {fs_low} must be attenuated by at least {atten_low} dB. "
        "Signals at {fs_high} must be attenuated by at least {atten_high} dB. "
        "Allow one op-amp to buffer the source; keep remaining components passive (R and C only).",

        # 7
        "Specify a band-pass filter for a high-impedance source with sharp skirt selectivity. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "A minimum of {atten_low} dB rejection is required at {fs_low}. "
        "A minimum of {atten_high} dB rejection is required at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum BOM cost.",

        # 8
        "Design a steep-skirt band-pass filter for a weak, high-impedance signal. "
        "Passband loss must not exceed {pb} dB between {fc_low} and {fc_high}. "
        "Stopband attenuation at {fs_low} must be at least {atten_low} dB. "
        "Stopband attenuation at {fs_high} must be at least {atten_high} dB. "
        "Use R, C, and one op-amp if necessary; keep the design as low-cost as possible.",

        # 9
        "Create a band-pass filter for a high-impedance transducer requiring strong out-of-band rejection. "
        "Signals between {fc_low} and {fc_high} must pass with less than {pb} dB insertion loss. "
        "Signals at {fs_low} must be suppressed by at least {atten_low} dB. "
        "Signals at {fs_high} must be suppressed by at least {atten_high} dB. "
        "Permitted components: resistors, capacitors, and one op-amp. Minimise component count.",

        # 10
        "A high-impedance source drives a band-pass filter with aggressive out-of-band attenuation requirements. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB loss. "
        "At {fs_low}, the circuit must deliver >= {atten_low} dB of attenuation. "
        "At {fs_high}, the circuit must deliver >= {atten_high} dB of attenuation. "
        "Use resistors, capacitors, and at most one op-amp; favour the simplest design that meets the spec.",
    ],

    # -- Buffered multi-stage: high-Z source + explicit low-Z load ------------
    "bufmulti_with_load": [
        # 1
        "Create a band-pass filter to condition a weak, high-impedance signal and drive a {load_r} ohm load. "
        "Signals from {fc_low} to {fc_high} must pass with less than {pb} dB loss. "
        "Frequencies at {fs_low} must be suppressed by at least {atten_low} dB. "
        "Frequencies at {fs_high} must be suppressed by at least {atten_high} dB. "
        "Allow one op-amp if necessary; otherwise restrict to passive R and C components.",

        # 2
        "Specify a band-pass filter for a high-impedance source driving a {load_r} ohm load. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "Stopband rejection at {fs_low} must be at least {atten_low} dB. "
        "Stopband rejection at {fs_high} must be at least {atten_high} dB. "
        "Components: resistors, capacitors, and one op-amp if required. Optimise for minimum BOM cost.",

        # 3
        "A signal chain begins at a high-impedance source and must drive a {load_r} ohm load after filtering. "
        "The band-pass filter must pass {fc_low} to {fc_high} with <= {pb} dB insertion loss, "
        "suppress {fs_low} by at least {atten_low} dB, and suppress {fs_high} by at least {atten_high} dB. "
        "Use one op-amp if needed; keep all other components passive (R and C only).",

        # 4
        "Build a band-pass filter to interface a high-impedance sensor to a {load_r} ohm load. "
        "The passband spans {fc_low} to {fc_high}; insertion loss must be below {pb} dB in the passband. "
        "A minimum of {atten_low} dB suppression is needed at {fs_low}. "
        "A minimum of {atten_high} dB suppression is needed at {fs_high}. "
        "Permitted components: R, C, and one op-amp if necessary. Keep the design as low-cost as possible.",

        # 5
        "Design a band-pass filter for a high-impedance signal source driving a {load_r} ohm load, "
        "with sharp transitions on both skirts. "
        "Signals from {fc_low} to {fc_high} must pass with <= {pb} dB loss. "
        "Signals at {fs_low} must be attenuated by at least {atten_low} dB. "
        "Signals at {fs_high} must be attenuated by at least {atten_high} dB. "
        "Allow one op-amp alongside passive R and C components; optimise for simplicity and low cost.",

        # 6
        "A high-impedance sensor output must drive a {load_r} ohm load through a steep band-pass filter. "
        "Pass frequencies from {fc_low} to {fc_high} with <= {pb} dB loss. "
        "Reject {fs_low} by at least {atten_low} dB and {fs_high} by at least {atten_high} dB. "
        "Use resistors, capacitors, and one op-amp; minimise total component count.",

        # 7
        "Specify a band-pass filter for a high-impedance source whose output feeds a {load_r} ohm stage. "
        "The passband must span {fc_low} to {fc_high} with less than {pb} dB insertion loss. "
        "At {fs_low}, the filter must deliver at least {atten_low} dB of attenuation. "
        "At {fs_high}, the filter must deliver at least {atten_high} dB of attenuation. "
        "Restrict to R, C, and at most one op-amp; favour the lowest-cost design.",

        # 8
        "Design a steep-skirt band-pass filter for a high-impedance sensor driving a {load_r} ohm load. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB insertion loss. "
        "A minimum of {atten_low} dB rejection is required at {fs_low}. "
        "A minimum of {atten_high} dB rejection is required at {fs_high}. "
        "Allow one op-amp to buffer the source; otherwise use only passive components.",

        # 9
        "A weak signal from a high-impedance source must be filtered and presented to a {load_r} ohm input. "
        "Signals from {fc_low} to {fc_high} must pass with <= {pb} dB attenuation. "
        "At {fs_low}, the suppression must be at least {atten_low} dB. "
        "At {fs_high}, the suppression must be at least {atten_high} dB. "
        "Use R, C, and one op-amp if necessary; keep the design as inexpensive as possible.",

        # 10
        "Create a high-attenuation band-pass filter for a high-impedance transducer feeding a {load_r} ohm load. "
        "Passband loss must be below {pb} dB between {fc_low} and {fc_high}. "
        "Stopband attenuation at {fs_low} must reach at least {atten_low} dB. "
        "Stopband attenuation at {fs_high} must reach at least {atten_high} dB. "
        "Permitted parts: resistors, capacitors, and at most one op-amp. Minimise BOM cost.",
    ],
}


# -----------------------------------------------------------------------------
# SPICE output-format post-amble
# -----------------------------------------------------------------------------

SPICE_POSTAMBLE = (
    "\n\n"
    "Provide the design as a SPICE netlist. "
    "The following node names are mandatory for automated simulation:\n"
    "  - Input node   : VIN\n"
    "  - Output node  : VOUT\n"
    "  - Ground / 0 V : GND\n"
    "Name all resistors with the prefix R (e.g. R1, R2), "
    "all capacitors with the prefix C (e.g. C1, C2), "
    "and any op-amp with the designator U1. "
    "Include a voltage source V1 connected between VIN and GND. "
    "End the netlist with a .END statement. "
    "Do not include a simulation command (.AC, .TRAN, etc.) in the netlist; "
    "the simulation will be configured externally."
)


# -----------------------------------------------------------------------------
# Main generator function
# -----------------------------------------------------------------------------

def generate_bpf_prompt(
    params: Optional[BPFParams] = None,
    template_index: Optional[int] = None,
) -> dict:
    """
    Generate a single BPF design prompt.

    Returns
    -------
    dict with keys:
        prompt       - complete prompt string (body + SPICE post-amble)
        task_type    - 'band_pass_filter'
        topology     - ground-truth topology label
        params       - BPFParams as a dict
        template_i   - template variant used (0-based)
    """
    if params is None:
        params = sample_params()

    topo = params.topology
    if topo == "buf":
        bank_key = "buf_with_load" if params.load_r_ohm else "buf_no_load"
    elif topo == "bufmulti":
        bank_key = "bufmulti_with_load" if params.load_r_ohm else "bufmulti_no_load"
    else:
        bank_key = topo

    bank = TEMPLATES[bank_key]

    if template_index is None:
        template_index = random.randrange(len(bank))
    else:
        template_index = template_index % len(bank)

    body = bank[template_index].format(
        fc_low=_fmt_hz(params.fc_low_hz),
        fc_high=_fmt_hz(params.fc_high_hz),
        fs_low=_fmt_hz(params.fs_low_hz),
        fs_high=_fmt_hz(params.fs_high_hz),
        pb=params.pb_loss_db,
        atten_low=params.atten_low_db,
        atten_high=params.atten_high_db,
        load_r=params.load_r_ohm,
    )

    return {
        "prompt": body + SPICE_POSTAMBLE,
        "task_type": "band_pass_filter",
        "topology": params.topology,
        "params": asdict(params),
        "template_i": template_index,
    }


def generate_dataset(
    n: int = 100,
    seed: Optional[int] = None,
    balanced: bool = True,
) -> list[dict]:
    """Generate a dataset of n BPF prompts."""
    if seed is not None:
        random.seed(seed)

    results = []

    if balanced:
        topos = ["single", "multi", "buf", "bufmulti"]
        flags = {
            "single":   dict(force_high_z=False, force_low_z=False, force_multi=False),
            "multi":    dict(force_high_z=False, force_low_z=False, force_multi=True),
            "buf":      dict(force_high_z=True,  force_low_z=None,  force_multi=False),
            "bufmulti": dict(force_high_z=True,  force_low_z=None,  force_multi=True),
        }
        for i in range(n):
            topo = topos[i % len(topos)]
            p = sample_params(**flags[topo])
            results.append(generate_bpf_prompt(params=p))
    else:
        for _ in range(n):
            results.append(generate_bpf_prompt())

    random.shuffle(results)
    return results


# -----------------------------------------------------------------------------
# Quick demo / CLI
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed_val  = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    print(f"Generating {n_samples} balanced BPF prompts (seed={seed_val})\n")
    print("=" * 72)

    dataset = generate_dataset(n=n_samples, seed=seed_val, balanced=True)

    for i, item in enumerate(dataset, 1):
        p = item["params"]
        print(
            f"\n[{i}/{n_samples}]  topology={item['topology'].upper():<10} "
            f"template={item['template_i']}\n"
            f"  fs_low={_fmt_hz(p['fs_low_hz'])}  "
            f"fc_low={_fmt_hz(p['fc_low_hz'])}  "
            f"fc_high={_fmt_hz(p['fc_high_hz'])}  "
            f"fs_high={_fmt_hz(p['fs_high_hz'])}\n"
            f"  rolloff_low={p['rolloff_low_dbpdec']} dB/dec  "
            f"n_low={p['n_stages_low']}  "
            f"atten_low={p['atten_low_db']} dB  |  "
            f"rolloff_high={p['rolloff_high_dbpdec']} dB/dec  "
            f"n_high={p['n_stages_high']}  "
            f"atten_high={p['atten_high_db']} dB"
        )
        print("-" * 72)
        print(item["prompt"])
        print("=" * 72)

    out_path = "bpf_dataset.json"
    with open(out_path, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"\nDataset written to {out_path}")