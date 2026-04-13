"""
notch_prompt_generator.py
=========================
Generates natural-language design prompts for notch (band-stop) filter circuits.
Each prompt uniquely specifies the required performance without naming
the topology, so it can be used to evaluate an LLM's circuit design ability.

Topologies covered
------------------
  single      - single passive twin-T (or bridged-T) notch network
  multi       - cascaded passive notch stages for greater notch depth
  buf         - single buffered notch stage (one op-amp)
  bufmulti    - multiple buffered notch stages (one op-amp)

Topology selection rules (deterministic given sampled params)
-------------------------------------------------------------
  buffered  = high_z_source OR low_z_load
  multi     = n_stages > 1   (derived from notch_depth_db threshold)
  ->  single    : not buffered, not multi
  ->  multi     : not buffered, multi
  ->  buf       : buffered, not multi
  ->  bufmulti  : buffered, multi

Parameter sampling order (guarantees physical consistency)
----------------------------------------------------------
  1. Sample notch_depth_db — attenuation at f_notch:
       single / buf    : from DEPTH_SINGLE_OPTIONS  (20–40 dB, 1 stage)
       multi / bufmulti: from DEPTH_MULTI_OPTIONS   (45–80 dB, 2–4 stages)
     n_stages is derived as ceil(notch_depth_db / 20).
  2. Sample rolloff_dbpdec independently for each skirt from
     ROLLOFF_OPTIONS (20, 40 dB/decade).  Each notch stage contributes
     ~20 dB/decade on each skirt; a 2-stage network contributes ~40, etc.
     Rolloff is capped at n_stages * 20 so it never exceeds what the
     topology can physically deliver.
  3. Sample f_notch (log-uniform).
     Sample bw_ratio -> half-bandwidth factor:
       fc_low  = f_notch / sqrt(bw_ratio)   (lower passband edge)
       fc_high = f_notch * sqrt(bw_ratio)   (upper passband edge)
     Sample fs_ratio:
       fs_low  = fc_low  / fs_ratio         (lower stopband, inside notch)
       fs_high = fc_high * fs_ratio         (upper stopband, inside notch)
     This guarantees fs_low < fc_low < f_notch < fc_high < fs_high.
  4. Derive:
       atten_low_db  = rolloff_low_dbpdec  * log10(fc_low  / fs_low)
       atten_high_db = rolloff_high_dbpdec * log10(fs_high / fc_high)
     Attenuation at the passband edges is defined as {pb} dB (the
     insertion-loss spec); attenuation deepens toward f_notch.

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

# Notch depth at f_notch — determines n_stages and 'multi' flag.
DEPTH_SINGLE_OPTIONS: list[float] = [20.0, 25.0, 30.0, 35.0, 40.0]   # 1 stage
DEPTH_MULTI_OPTIONS:  list[float] = [45.0, 50.0, 60.0, 70.0, 80.0]   # 2–4 stages

# Per-skirt rolloff options (dB/decade).
# Available choices are capped per-sample to n_stages * 20.
ROLLOFF_OPTIONS: list[float] = [20.0, 40.0, 60.0, 80.0]

# Notch centre frequency range (Hz) — sampled on log scale.
F_NOTCH_LOG_RANGE = (100, 50_000)

# Bandwidth ratio: fc_high / fc_low = bw_ratio, centred on f_notch.
# Larger ratio -> wider notch passband edges relative to f_notch.
BW_RATIO_OPTIONS = [2, 3, 4, 5, 10]

# Stopband ratio (inward from passband edge toward f_notch):
#   fs_low  = fc_low  / fs_ratio   (fs_low  < fc_low,  closer to f_notch)
#   fs_high = fc_high * fs_ratio   (fs_high > fc_high, closer to ... wait,
#             actually for a notch the stopband is INSIDE the passband edges,
#             so fs is between fc and f_notch, not outside.)
#
# Correct geometry for a notch:
#   passband : f < fc_low  OR  f > fc_high      (far from f_notch)
#   stopband : fs_low <= f <= fs_high            (close to f_notch)
#   fc_low > fs_low > f_notch < fs_high < fc_high
#
# So the stopband frequencies are BETWEEN the passband edges and f_notch:
#   fs_low  = fc_low  / fs_ratio   (fs_low  < fc_low,  inside the notch band)
#   fs_high = fc_high * ... NO.
#
# Wait — let's be precise.  For a notch filter:
#   Deep attenuation NEAR f_notch.
#   Low attenuation FAR from f_notch (passband).
#   fc_low  = lower -pb_dB frequency  (passband edge, BELOW notch)
#   fc_high = upper -pb_dB frequency  (passband edge, ABOVE notch)
#   fs_low  = lower stopband freq     (close to notch, ABOVE fc_low)
#   fs_high = upper stopband freq     (close to notch, BELOW fc_high)
#   Ordering: fc_low < fs_low < f_notch < fs_high < fc_high
#
# fs_low  = fc_low  * fs_ratio   (fs_ratio > 1, pushes inward toward f_notch)
# fs_high = fc_high / fs_ratio   (fs_ratio > 1, pushes inward toward f_notch)
# Constraint: fs_low < f_notch  and  fs_high > f_notch, guaranteed when
#   fs_ratio < sqrt(bw_ratio)  (checked in sampler).
FS_RATIO_OPTIONS = [1.2, 1.5, 1.7, 2.0]    # must stay < sqrt(bw_ratio)

# Passband ripple options (dB)
PB_LOSS_OPTIONS = [0.5, 1.0, 1.0, 1.0, 2.0, 3.0]

# Load impedances used in low-Z scenarios
LOW_Z_LOAD_OPTIONS = [500, 1_000, 1_500, 2_000, 4_700]


# -----------------------------------------------------------------------------
# Parameter dataclass
# -----------------------------------------------------------------------------

@dataclass
class NotchParams:
    topology: str                   # 'single' | 'multi' | 'buf' | 'bufmulti'
    f_notch_hz: float               # centre of the notch
    fc_low_hz: float                # lower passband edge  (-pb_loss_db point)
    fc_high_hz: float               # upper passband edge  (-pb_loss_db point)
    fs_low_hz: float                # lower stopband freq  (fc_low < fs_low < f_notch)
    fs_high_hz: float               # upper stopband freq  (f_notch < fs_high < fc_high)
    bw_ratio: float                 # fc_high_hz / fc_low_hz
    fs_ratio: float                 # fs_low / fc_low = fc_high / fs_high
    pb_loss_db: float               # max passband insertion loss (dB)
    notch_depth_db: float           # attenuation at f_notch
    rolloff_low_dbpdec: float       # rolloff rate on the lower skirt
    rolloff_high_dbpdec: float      # rolloff rate on the upper skirt
    atten_low_db: float             # derived attenuation at fs_low
    atten_high_db: float            # derived attenuation at fs_high
    n_stages: int                   # number of notch stages
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


def _atten(rolloff_dbpdec: float, f_outer: float, f_inner: float) -> float:
    """
    Attenuation at f_inner relative to f_outer for a skirt with the given
    rolloff rate.  For a notch:
      lower skirt: f_outer = fc_low,  f_inner = fs_low  (fs_low > fc_low)
      upper skirt: f_outer = fc_high, f_inner = fs_high (fs_high < fc_high)
    In both cases ratio = max/min > 1 so log10 is positive.
    """
    ratio = max(f_outer, f_inner) / min(f_outer, f_inner)
    return round(rolloff_dbpdec * math.log10(ratio), 1)


# -----------------------------------------------------------------------------
# Sampler
# -----------------------------------------------------------------------------

def sample_params(
    force_high_z: Optional[bool] = None,
    force_low_z:  Optional[bool] = None,
    force_multi:  Optional[bool] = None,
) -> NotchParams:
    """
    Sample a random-but-valid set of notch filter design parameters.

    Sampling order
    --------------
    1. Decide buffering (high_z / low_z).
    2. Decide whether multi-stage (force_multi or random).
    3. Sample notch_depth_db; derive n_stages = ceil(depth / 20).
    4. Sample rolloff for each skirt, capped at n_stages * 20 dB/decade.
    5. Sample f_notch, bw_ratio -> fc_low, fc_high (symmetric about f_notch).
    6. Sample fs_ratio from valid options (must satisfy fs_ratio < sqrt(bw_ratio))
       -> fs_low = fc_low * fs_ratio, fs_high = fc_high / fs_ratio.
       Retry fs_ratio if constraint is violated.
    7. Derive atten_low_db, atten_high_db.
    8. Sample pb_loss, load_r.
    9. Assign topology label.
    """
    # --- Step 1: buffering ---------------------------------------------------
    high_z = force_high_z if force_high_z is not None else (random.random() < 0.4)
    low_z  = force_low_z  if force_low_z  is not None else (random.random() < 0.35)
    buffered = high_z or low_z

    # --- Step 2: multi-stage decision ----------------------------------------
    multi = force_multi if force_multi is not None else (random.random() < 0.5)

    # --- Step 3: notch depth and stage count ---------------------------------
    if multi:
        notch_depth_db = random.choice(DEPTH_MULTI_OPTIONS)
    else:
        notch_depth_db = random.choice(DEPTH_SINGLE_OPTIONS)

    n_stages = max(1, math.ceil(notch_depth_db / 20.0))

    # --- Step 4: per-skirt rolloff (capped by topology) ----------------------
    max_rolloff = n_stages * 20.0
    valid_rolloffs = [r for r in ROLLOFF_OPTIONS if r <= max_rolloff]

    rolloff_low  = random.choice(valid_rolloffs)
    rolloff_high = random.choice(valid_rolloffs)

    # --- Steps 5 & 6: frequencies — resample until strict ordering holds ------
    # Required: fc_low < fs_low < f_notch < fs_high < fc_high (all strict).
    # Rounding to 1 sig fig can collapse adjacent values, so we retry.
    f_notch_hz = _log_sample_hz(*F_NOTCH_LOG_RANGE)
    fc_low_hz = fs_low_hz = fc_high_hz = fs_high_hz = 0.0
    bw_ratio = fs_ratio = 2
    for _ in range(50):
        bw_ratio   = random.choice(BW_RATIO_OPTIONS)
        fc_low_hz  = _round_1sf(f_notch_hz / math.sqrt(bw_ratio))
        fc_high_hz = _round_1sf(f_notch_hz * math.sqrt(bw_ratio))

        sqrt_bw = math.sqrt(bw_ratio)
        valid_fs_ratios = [r for r in FS_RATIO_OPTIONS if r < sqrt_bw]
        if not valid_fs_ratios:
            continue

        fs_ratio   = random.choice(valid_fs_ratios)
        fs_low_hz  = _round_1sf(fc_low_hz  * fs_ratio)
        fs_high_hz = _round_1sf(fc_high_hz / fs_ratio)

        if fc_low_hz < fs_low_hz < f_notch_hz < fs_high_hz < fc_high_hz:
            break
    else:
        # Fallback: wide notch that always separates cleanly after rounding
        bw_ratio   = 10
        fs_ratio   = 1.5
        fc_low_hz  = _round_1sf(f_notch_hz / math.sqrt(bw_ratio))
        fc_high_hz = _round_1sf(f_notch_hz * math.sqrt(bw_ratio))
        fs_low_hz  = _round_1sf(fc_low_hz  * fs_ratio)
        fs_high_hz = _round_1sf(fc_high_hz / fs_ratio)

    # --- Step 7: derived attenuations ----------------------------------------
    atten_low_db  = _atten(rolloff_low,  fc_low_hz,  fs_low_hz)
    atten_high_db = _atten(rolloff_high, fc_high_hz, fs_high_hz)

    # --- Step 8: passband loss and load --------------------------------------
    pb_loss = random.choice(PB_LOSS_OPTIONS)
    load_r  = random.choice(LOW_Z_LOAD_OPTIONS) if (buffered and low_z) else None

    # --- Step 9: topology label ----------------------------------------------
    if not buffered and not multi:
        topo = "single"
    elif not buffered and multi:
        topo = "multi"
    elif buffered and not multi:
        topo = "buf"
    else:
        topo = "bufmulti"

    return NotchParams(
        topology=topo,
        f_notch_hz=f_notch_hz,
        fc_low_hz=fc_low_hz,
        fc_high_hz=fc_high_hz,
        fs_low_hz=fs_low_hz,
        fs_high_hz=fs_high_hz,
        bw_ratio=bw_ratio,
        fs_ratio=fs_ratio,
        pb_loss_db=pb_loss,
        notch_depth_db=notch_depth_db,
        rolloff_low_dbpdec=rolloff_low,
        rolloff_high_dbpdec=rolloff_high,
        atten_low_db=atten_low_db,
        atten_high_db=atten_high_db,
        n_stages=n_stages,
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
#   {f_notch}     - notch centre frequency (formatted)
#   {fc_low}      - lower passband edge (formatted)   signal passes BELOW this
#   {fc_high}     - upper passband edge (formatted)   signal passes ABOVE this
#   {fs_low}      - lower stopband freq (formatted)   fc_low  < fs_low  < f_notch
#   {fs_high}     - upper stopband freq (formatted)   f_notch < fs_high < fc_high
#   {pb}          - passband insertion loss limit (dB)
#   {depth}       - notch depth at f_notch (dB)
#   {atten_low}   - attenuation at fs_low  (dB)
#   {atten_high}  - attenuation at fs_high (dB)
#   {load_r}      - load resistance in ohm (with-load banks only)
#
# Templates deliberately do NOT name the topology.
# Passband = outside the notch (f < fc_low OR f > fc_high).
# Stopband = inside the notch  (fs_low <= f <= fs_high).
# -----------------------------------------------------------------------------

TEMPLATES: dict[str, list[str]] = {

    # -- Single passive notch stage -------------------------------------------
    "single": [
        # 1
        "Design a notch filter to reject a specific interfering frequency. "
        "Signals below {fc_low} and above {fc_high} must pass with no more than {pb} dB of insertion loss. "
        "Interference at {f_notch} must be attenuated by at least {depth} dB. "
        "The attenuation must reach {atten_low} dB by {fs_low} and {atten_high} dB by {fs_high}. "
        "Use only resistors and capacitors; minimise component count.",

        # 2
        "Create a band-stop filter to suppress a narrowband interferer. "
        "The passband must extend from DC to {fc_low} and from {fc_high} upward, "
        "each with less than {pb} dB insertion loss. "
        "At {f_notch}, at least {depth} dB of rejection is required. "
        "Attenuation must be >= {atten_low} dB at {fs_low} and >= {atten_high} dB at {fs_high}. "
        "No active components; optimise for minimum cost.",

        # 3
        "Specify a passive RC notch network to eliminate a tonal interference signal. "
        "Frequencies outside the range {fs_low} to {fs_high} must be passed with <= {pb} dB loss. "
        "The notch at {f_notch} must provide at least {depth} dB of attenuation. "
        "Transition-band attenuation must reach {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use only resistors and capacitors; keep the design as simple as possible.",

        # 4
        "A signal conditioning circuit must suppress a known interference tone "
        "while passing all other frequencies. "
        "Signals below {fc_low} and above {fc_high} must experience no more than {pb} dB of loss. "
        "The tone at {f_notch} must be reduced by at least {depth} dB. "
        "By {fs_low} and {fs_high} the attenuation must reach {atten_low} dB and {atten_high} dB respectively. "
        "Permitted components: resistors and capacitors only.",

        # 5
        "Design a notch filter for a standard-impedance signal path. "
        "Pass signals outside the notch band ({fc_low} and below, {fc_high} and above) "
        "with under {pb} dB loss. "
        "Provide at least {depth} dB of attenuation at {f_notch}. "
        "The skirts must reach {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a band-stop filter to protect a downstream circuit from a narrowband interferer. "
        "The passband insertion loss must stay below {pb} dB for frequencies below {fc_low} "
        "and above {fc_high}. "
        "At {f_notch}, the rejection must be at least {depth} dB. "
        "Attenuation at {fs_low} must be >= {atten_low} dB; at {fs_high} >= {atten_high} dB. "
        "Restrict the design to resistors and capacitors; use as few as possible.",

        # 7
        "A passive notch filter is required to remove a single-frequency interference signal. "
        "Signals at {fc_low} and below, and at {fc_high} and above, should experience "
        "at most {pb} dB of loss. "
        "The notch centre at {f_notch} must achieve >= {depth} dB attenuation. "
        "The skirts must provide {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "The solution must be purely passive and as inexpensive as possible.",

        # 8
        "Design a notch filter to remove a narrowband tone before sampling. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB insertion loss. "
        "A minimum of {depth} dB rejection is required at the notch centre {f_notch}. "
        "Transition-band requirements: {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A single-frequency rejection filter is required for an interference cancellation application. "
        "It must pass frequencies below {fc_low} and above {fc_high} with less than {pb} dB attenuation "
        "while rejecting {f_notch} by at least {depth} dB. "
        "Skirt attenuation: >= {atten_low} dB at {fs_low}, >= {atten_high} dB at {fs_high}. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a notch filter design for a general-purpose tonal interference rejection application. "
        "The passband must be within {pb} dB of unity gain for all frequencies "
        "below {fc_low} and above {fc_high}. "
        "At {f_notch} the filter must deliver >= {depth} dB of attenuation. "
        "Skirt specs: {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage passive notch ---------------------------------------------
    "multi": [
        # 1
        "Design a deep-notch band-stop filter for a signal conditioning application. "
        "Signals below {fc_low} and above {fc_high} must pass with no more than {pb} dB insertion loss. "
        "The notch at {f_notch} must provide at least {depth} dB of rejection. "
        "The skirts must achieve {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use only resistors and capacitors; minimise total component count.",

        # 2
        "Create a high-attenuation notch filter to strongly suppress a narrowband interferer. "
        "Signals outside the notch ({fc_low} and below, {fc_high} and above) must pass "
        "with less than {pb} dB loss. "
        "The circuit must provide at least {depth} dB of rejection at {f_notch}. "
        "Skirt attenuation must reach {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "No active components are allowed; keep the design as cost-effective as possible.",

        # 3
        "Specify a passive RC notch filter for a noise-sensitive signal path requiring deep rejection. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB loss. "
        "A minimum of {depth} dB attenuation is required at {f_notch}. "
        "Transition requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use only resistors and capacitors; use the fewest stages that meet the spec.",

        # 4
        "Design a passive band-stop filter to provide deep rejection of a specific interference tone. "
        "Pass all frequencies below {fc_low} and above {fc_high} with under {pb} dB loss. "
        "At {f_notch}, the attenuation must be at least {depth} dB. "
        "Skirt requirements: {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Permitted components: resistors and capacitors only. Optimise for minimum cost.",

        # 5
        "A signal must have a specific frequency deeply suppressed before entering a sensitive circuit. "
        "The passband (outside the notch) must stay within {pb} dB of 0 dB gain. "
        "At {f_notch}, at least {depth} dB of rejection is required. "
        "The lower skirt must reach {atten_low} dB at {fs_low}; "
        "the upper skirt must reach {atten_high} dB at {fs_high}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a notch filter with deep rejection for an EMC interference suppression application. "
        "Frequencies below {fc_low} and above {fc_high} must be passed with <= {pb} dB attenuation. "
        "The interference tone at {f_notch} must be reduced by a minimum of {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use only resistors and capacitors; favour the simplest topology that meets these figures.",

        # 7
        "A passive notch network is required to achieve high rejection of a single-frequency interference. "
        "The insertion loss must be below {pb} dB in the passband (below {fc_low} and above {fc_high}). "
        "The notch at {f_notch} must achieve >= {depth} dB of attenuation. "
        "Skirt requirements: >= {atten_low} dB at {fs_low}, >= {atten_high} dB at {fs_high}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive deep-notch filter for a data acquisition front end. "
        "Signals outside the stop band must pass with less than {pb} dB loss "
        "(passband edges at {fc_low} and {fc_high}). "
        "Signals at {f_notch} must be suppressed by at least {depth} dB. "
        "Skirt attenuation: {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Only R and C components; favour the lowest-cost design.",

        # 9
        "Provide a high-rejection passive notch filter design for a measurement system. "
        "The passband below {fc_low} and above {fc_high} must have a maximum of {pb} dB insertion loss. "
        "At {f_notch}, a minimum of {depth} dB attenuation is required. "
        "Lower skirt: {atten_low} dB at {fs_low}. Upper skirt: {atten_high} dB at {fs_high}. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A notch filter is needed with demanding rejection at a specific interference frequency. "
        "Frequencies below {fc_low} and above {fc_high} must be passed with <= {pb} dB loss. "
        "At {f_notch} the filter must attenuate signals by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single notch: high-Z source, no load ------------------------
    "buf_no_load": [
        # 1
        "Design a notch filter for a high-impedance signal source. "
        "Signals below {fc_low} and above {fc_high} must pass with no more than {pb} dB of insertion loss. "
        "Interference at {f_notch} must be attenuated by at least {depth} dB. "
        "Skirt requirements: {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp for impedance buffering. "
        "Keep the circuit as simple and inexpensive as possible.",

        # 2
        "A signal from a high-impedance source must have a specific tone removed before further processing. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB attenuation. "
        "Rejection at {f_notch} must be at least {depth} dB. "
        "Skirt attenuation: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use passive R and C; add one op-amp only where the impedance requires it.",

        # 3
        "A measurement system has a high-impedance source that picks up a specific tonal interferer. "
        "A notch filter is required that passes all frequencies except the range {fs_low} to {fs_high}, "
        "with <= {pb} dB passband loss, {depth} dB rejection at {f_notch}, "
        "{atten_low} dB at {fs_low}, and {atten_high} dB at {fs_high}. "
        "Use one op-amp if required; otherwise use only resistors and capacitors.",

        # 4
        "Build a notch filter that can accept a signal from a high-impedance source. "
        "Frequencies outside the notch band must pass with no more than {pb} dB attenuation "
        "(passband edges at {fc_low} and {fc_high}). "
        "The notch at {f_notch} must achieve at least {depth} dB rejection. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and optionally one op-amp; minimise component count.",

        # 5
        "Design a notch filter for a high-impedance source requiring impedance buffering. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB insertion loss. "
        "Rejection at {f_notch} must be at least {depth} dB. "
        "Skirt attenuation: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors and capacitors; one op-amp is allowed if necessary.",

        # 6
        "Create a notch filter to remove a tonal interferer from a weak, high-impedance signal. "
        "Signals below {fc_low} and above {fc_high} must pass with less than {pb} dB loss. "
        "The interference at {f_notch} must be suppressed by at least {depth} dB. "
        "Skirts must reach {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Permitted components: resistors, capacitors, and at most one op-amp. Minimise cost.",

        # 7
        "Specify a notch filter for a high-impedance sensor output. "
        "The passband must extend up to {fc_low} and from {fc_high} upward with <= {pb} dB loss. "
        "The notch at {f_notch} must reach at least {depth} dB attenuation. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 8
        "A high-impedance transducer output needs a tone removed before digitisation. "
        "The filter must pass signals below {fc_low} and above {fc_high} with under {pb} dB loss, "
        "achieve {depth} dB rejection at {f_notch}, "
        "and meet skirt specs of {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Allow one op-amp alongside passive R and C; keep the design simple.",

        # 9
        "Provide a notch filter design for a high-impedance signal source. "
        "The insertion loss must be below {pb} dB in the passband (below {fc_low} and above {fc_high}). "
        "A minimum of {depth} dB attenuation is required at {f_notch}. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 10
        "Design a notch filter for a sensor with high output impedance. "
        "Signals outside the notch band must be passed with <= {pb} dB loss "
        "(passband edges at {fc_low} and {fc_high}). "
        "Signals at {f_notch} must be attenuated by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum part count.",
    ],

    # -- Buffered single notch: high-Z source + explicit low-Z load -----------
    "buf_with_load": [
        # 1
        "Create a notch filter to condition a weak signal from a high-impedance transducer "
        "and drive a {load_r} ohm load. "
        "Signals outside the notch (below {fc_low} and above {fc_high}) must pass with < {pb} dB loss. "
        "Interference at {f_notch} must be suppressed by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Permitted components: resistors, capacitors, and at most one op-amp.",

        # 2
        "Specify a notch filter for a high-impedance sensor output feeding a {load_r} ohm load. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB insertion loss. "
        "Notch depth at {f_notch} must be at least {depth} dB. "
        "Skirt attenuation: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 3
        "Design a notch filter to interface a high-impedance source to a {load_r} ohm circuit. "
        "Pass signals below {fc_low} and above {fc_high} with under {pb} dB insertion loss. "
        "Provide >= {depth} dB of rejection at {f_notch}. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Components: resistors, capacitors, and one op-amp if needed. Minimise cost.",

        # 4
        "Design a notch filter for a sensor interface where the source impedance is high "
        "and the load is {load_r} ohm. "
        "The passband must span DC to {fc_low} and {fc_high} and above with < {pb} dB loss. "
        "At {f_notch}, at least {depth} dB of suppression is needed. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Allow resistors, capacitors, and at most one op-amp; keep the design simple.",

        # 5
        "Provide a notch filter design for a high-impedance signal source driving a {load_r} ohm load. "
        "Passband insertion loss must be below {pb} dB (edges at {fc_low} and {fc_high}). "
        "Notch depth at {f_notch}: at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 6
        "A high-impedance sensor feeds a {load_r} ohm input stage. "
        "Design a notch filter between them that passes signals outside the notch band "
        "with <= {pb} dB loss (edges at {fc_low} and {fc_high}), "
        "rejects {f_notch} by at least {depth} dB, "
        "and meets skirt specs of {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and one op-amp if necessary; minimise component count.",

        # 7
        "Design a notch filter for a high-impedance signal source whose output "
        "must drive a {load_r} ohm load without degrading in-band signals. "
        "Passband edges: {fc_low} and {fc_high} with <= {pb} dB insertion loss. "
        "Notch: {depth} dB at {f_notch}. Skirts: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use R, C, and at most one op-amp; optimise for low cost.",

        # 8
        "A weak, high-impedance signal must have a tone suppressed and be delivered to a {load_r} ohm load. "
        "The filter must pass below {fc_low} and above {fc_high} with < {pb} dB loss, "
        "achieve {depth} dB rejection at {f_notch}, "
        "and satisfy skirt specs of {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Allow one op-amp if needed; otherwise restrict to passive components.",

        # 9
        "Specify a notch filter to buffer a high-impedance source and drive a {load_r} ohm load. "
        "Signals outside the notch band (edges at {fc_low} and {fc_high}) must pass with <= {pb} dB. "
        "The notch at {f_notch} must achieve at least {depth} dB attenuation. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and optionally one op-amp; favour the simplest design.",

        # 10
        "Build a notch filter for a high-impedance sensor output connected to a {load_r} ohm input. "
        "The circuit must pass outside the notch band (edges at {fc_low} and {fc_high}) with under {pb} dB loss, "
        "deliver >= {depth} dB rejection at {f_notch}, "
        "and meet {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Permitted parts: R, C, and one op-amp if required. Keep BOM cost minimal.",
    ],

    # -- Buffered multi-stage notch: high-Z source, no load -------------------
    "bufmulti_no_load": [
        # 1
        "Design a deep-notch filter for a high-impedance signal source. "
        "Signals below {fc_low} and above {fc_high} must pass with no more than {pb} dB insertion loss. "
        "At {f_notch}, at least {depth} dB of attenuation is required. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp. Minimise cost and component count.",

        # 2
        "A high-impedance transducer feeds a notch filter requiring deep tonal rejection. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB attenuation. "
        "The attenuation at {f_notch} must be >= {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp; "
        "use the fewest stages that meet the specification.",

        # 3
        "Design a notch filter with deep rejection for a high-impedance sensor interface. "
        "The passband must span DC to {fc_low} and {fc_high} upward, with under {pb} dB loss. "
        "Provide >= {depth} dB of rejection at {f_notch}. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "An op-amp is permitted to handle source impedance; use only passive components otherwise.",

        # 4
        "Design a notch filter for a high-impedance signal source with demanding rejection requirements. "
        "Frequencies outside the notch (below {fc_low} and above {fc_high}) must pass with < {pb} dB loss. "
        "At {f_notch}, the filter must deliver at least {depth} dB of attenuation. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Restrict components to resistors, capacitors, and at most one op-amp; minimise part count.",

        # 5
        "Provide a notch filter design for a high-impedance source requiring both "
        "impedance buffering and deep tonal rejection. "
        "Passband insertion loss must be below {pb} dB (edges at {fc_low} and {fc_high}). "
        "Notch depth at {f_notch}: at least {depth} dB. "
        "Skirts: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and one op-amp; minimise the total number of components.",

        # 6
        "A high-impedance sensor signal requires deep notch filtering before digitisation. "
        "Signals outside the notch band must pass with <= {pb} dB loss "
        "(passband edges at {fc_low} and {fc_high}). "
        "Signals at {f_notch} must be attenuated by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Allow one op-amp to buffer the source; keep remaining components passive.",

        # 7
        "Specify a deep-notch filter for a high-impedance source requiring strong tonal suppression. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB insertion loss. "
        "A minimum of {depth} dB rejection is required at {f_notch}. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum BOM cost.",

        # 8
        "Design a multi-stage notch filter for a weak, high-impedance signal. "
        "Passband loss must not exceed {pb} dB (edges at {fc_low} and {fc_high}). "
        "Notch depth at {f_notch} must be at least {depth} dB. "
        "Skirt attenuation: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use R, C, and one op-amp if necessary; keep the design as low-cost as possible.",

        # 9
        "Create a deep notch filter for a high-impedance transducer requiring strong tonal interference rejection. "
        "Signals outside the stop band must pass with < {pb} dB insertion loss "
        "(edges at {fc_low} and {fc_high}). "
        "Signals at {f_notch} must be suppressed by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Permitted components: resistors, capacitors, and one op-amp. Minimise component count.",

        # 10
        "A high-impedance source drives a notch filter with aggressive rejection requirements. "
        "The passband (below {fc_low} and above {fc_high}) must have <= {pb} dB loss. "
        "At {f_notch}, the circuit must deliver >= {depth} dB of attenuation. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and at most one op-amp; favour the simplest design.",
    ],

    # -- Buffered multi-stage notch: high-Z source + explicit low-Z load ------
    "bufmulti_with_load": [
        # 1
        "Create a deep-notch filter to condition a weak, high-impedance signal "
        "and drive a {load_r} ohm load. "
        "Signals outside the notch (below {fc_low} and above {fc_high}) must pass with < {pb} dB loss. "
        "The tone at {f_notch} must be suppressed by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Allow one op-amp if necessary; otherwise restrict to passive R and C components.",

        # 2
        "Specify a deep-notch filter for a high-impedance source driving a {load_r} ohm load. "
        "Passband edges at {fc_low} and {fc_high} with <= {pb} dB insertion loss. "
        "Notch depth at {f_notch}: >= {depth} dB. "
        "Skirt rejection: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Components: resistors, capacitors, and one op-amp if required. Optimise for minimum BOM cost.",

        # 3
        "A signal chain begins at a high-impedance source and must drive a {load_r} ohm load. "
        "A notch filter is required between them that passes below {fc_low} and above {fc_high} "
        "with <= {pb} dB loss, rejects {f_notch} by at least {depth} dB, "
        "and meets skirt specs of {atten_low} dB at {fs_low} and {atten_high} dB at {fs_high}. "
        "Use one op-amp if needed; keep all other components passive.",

        # 4
        "Build a deep-notch filter to interface a high-impedance sensor to a {load_r} ohm load. "
        "Insertion loss must be below {pb} dB in the passband (edges at {fc_low} and {fc_high}). "
        "Minimum rejection at {f_notch}: {depth} dB. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Permitted components: R, C, and one op-amp if necessary. Keep the design low-cost.",

        # 5
        "Design a deep-notch filter for a high-impedance signal source driving a {load_r} ohm load. "
        "Signals outside the stop band (below {fc_low} and above {fc_high}) must pass with <= {pb} dB loss. "
        "Signals at {f_notch} must be attenuated by at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Allow one op-amp alongside passive R and C; optimise for simplicity and low cost.",

        # 6
        "A high-impedance sensor output must drive a {load_r} ohm load through a deep notch filter. "
        "Pass all frequencies outside the notch (edges at {fc_low} and {fc_high}) with <= {pb} dB loss. "
        "Reject {f_notch} by at least {depth} dB. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use resistors, capacitors, and one op-amp; minimise total component count.",

        # 7
        "Specify a deep-notch filter for a high-impedance source whose output feeds a {load_r} ohm stage. "
        "The passband (below {fc_low} and above {fc_high}) must have < {pb} dB insertion loss. "
        "At {f_notch}, the filter must deliver at least {depth} dB of attenuation. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Restrict to R, C, and at most one op-amp; favour the lowest-cost design.",

        # 8
        "Design a deep-notch filter for a high-impedance sensor driving a {load_r} ohm load. "
        "Passband edges at {fc_low} and {fc_high} with <= {pb} dB insertion loss. "
        "Notch depth at {f_notch}: at least {depth} dB. "
        "Skirt requirements: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Allow one op-amp to buffer the source; otherwise use only passive components.",

        # 9
        "A weak signal from a high-impedance source must be notch-filtered and presented "
        "to a {load_r} ohm input. "
        "Signals below {fc_low} and above {fc_high} must pass with <= {pb} dB attenuation. "
        "At {f_notch}, the suppression must be at least {depth} dB. "
        "Skirt specs: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
        "Use R, C, and one op-amp if necessary; keep the design as inexpensive as possible.",

        # 10
        "Create a deep-notch filter for a high-impedance transducer feeding a {load_r} ohm load. "
        "Passband loss must be below {pb} dB (edges at {fc_low} and {fc_high}). "
        "Notch depth at {f_notch}: >= {depth} dB. "
        "Skirt attenuation: {atten_low} dB at {fs_low}, {atten_high} dB at {fs_high}. "
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

def generate_notch_prompt(
    params: Optional[NotchParams] = None,
    template_index: Optional[int] = None,
) -> dict:
    """
    Generate a single notch filter design prompt.

    Returns
    -------
    dict with keys:
        prompt       - complete prompt string (body + SPICE post-amble)
        task_type    - 'notch_filter'
        topology     - ground-truth topology label
        params       - NotchParams as a dict
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
        f_notch=_fmt_hz(params.f_notch_hz),
        fc_low=_fmt_hz(params.fc_low_hz),
        fc_high=_fmt_hz(params.fc_high_hz),
        fs_low=_fmt_hz(params.fs_low_hz),
        fs_high=_fmt_hz(params.fs_high_hz),
        pb=params.pb_loss_db,
        depth=params.notch_depth_db,
        atten_low=params.atten_low_db,
        atten_high=params.atten_high_db,
        load_r=params.load_r_ohm,
    )

    return {
        "prompt": body + SPICE_POSTAMBLE,
        "task_type": "notch_filter",
        "topology": params.topology,
        "params": asdict(params),
        "template_i": template_index,
    }


def generate_dataset(
    n: int = 100,
    seed: Optional[int] = None,
    balanced: bool = True,
) -> list[dict]:
    """Generate a dataset of n notch filter prompts."""
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
            results.append(generate_notch_prompt(params=p))
    else:
        for _ in range(n):
            results.append(generate_notch_prompt())

    random.shuffle(results)
    return results


# -----------------------------------------------------------------------------
# Quick demo / CLI
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed_val  = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    print(f"Generating {n_samples} balanced notch filter prompts (seed={seed_val})\n")
    print("=" * 72)

    dataset = generate_dataset(n=n_samples, seed=seed_val, balanced=True)

    for i, item in enumerate(dataset, 1):
        p = item["params"]
        print(
            f"\n[{i}/{n_samples}]  topology={item['topology'].upper():<10} "
            f"template={item['template_i']}\n"
            f"  fc_low={_fmt_hz(p['fc_low_hz'])}  "
            f"fs_low={_fmt_hz(p['fs_low_hz'])}  "
            f"f_notch={_fmt_hz(p['f_notch_hz'])}  "
            f"fs_high={_fmt_hz(p['fs_high_hz'])}  "
            f"fc_high={_fmt_hz(p['fc_high_hz'])}\n"
            f"  depth={p['notch_depth_db']} dB  n_stages={p['n_stages']}  "
            f"rolloff_low={p['rolloff_low_dbpdec']} dB/dec  atten_low={p['atten_low_db']} dB  |  "
            f"rolloff_high={p['rolloff_high_dbpdec']} dB/dec  atten_high={p['atten_high_db']} dB"
        )
        print("-" * 72)
        print(item["prompt"])
        print("=" * 72)

    out_path = "notch_dataset.json"
    with open(out_path, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"\nDataset written to {out_path}")