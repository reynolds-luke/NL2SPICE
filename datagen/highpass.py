"""
hpf_prompt_generator.py
=======================
Generates natural-language design prompts for high-pass filter circuits.
Each prompt uniquely specifies the required performance without naming
the topology, so it can be used to evaluate an LLM's circuit design ability.

Topologies covered
------------------
  single      - single-stage RC (passive)
  multi       - multi-stage RC (passive, higher order)
  buf         - single-stage buffered RC (one op-amp)
  bufmulti    - multi-stage buffered RC (one op-amp + multiple RC stages)

Topology selection rules (deterministic given sampled params)
-------------------------------------------------------------
  buffered  = high_z_source OR low_z_load
  multi     = n_stages > 1   (derived from rolloff_dbpdec)
  ->  single    : not buffered, not multi
  ->  multi     : not buffered, multi
  ->  buf       : buffered, not multi
  ->  bufmulti  : buffered, multi

Parameter sampling order (guarantees physical consistency)
----------------------------------------------------------
  1. Sample rolloff_dbpdec from valid per-topology set:
       single / buf    : always 20 dB/decade  (1 RC stage)
       multi / bufmulti: one of {40, 60, 80, 100} dB/decade  (2–5 stages)
  2. Sample fc_hz (log-uniform) and fs_ratio -> fs_hz = fc_hz / fs_ratio
     For a HPF the stopband is BELOW the corner, so fs < fc always.
  3. Derive atten_db = rolloff_dbpdec * log10(fc_hz / fs_hz)
     (decades are measured downward from corner to stopband)
     This is always physically achievable by construction.

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

# Valid rolloff rates per topology class (dB/decade).
# Each rate corresponds to n = rate/20 cascaded RC stages.
ROLLOFF_SINGLE_DBPDEC: float = 20.0
ROLLOFF_MULTI_OPTIONS: list[float] = [40.0, 60.0, 80.0, 100.0]  # 2–5 stages

# Corner frequency range (Hz) — sampled on log scale
FC_LOG_RANGE = (100, 100_000)

# Stopband frequency ratio relative to corner (fs = fc / ratio, so fs < fc).
# Identical ratio options as the LPF; direction is inverted in the sampler.
FS_RATIO_OPTIONS = [2, 3, 4, 5, 10]

# Passband ripple options (dB)
PB_LOSS_OPTIONS = [0.5, 1.0, 1.0, 1.0, 2.0, 3.0]   # weighted towards 1 dB

# Load impedances used in low-Z scenarios
LOW_Z_LOAD_OPTIONS = [500, 1_000, 1_500, 2_000, 4_700]


# -----------------------------------------------------------------------------
# Parameter dataclass
# -----------------------------------------------------------------------------

@dataclass
class HPFParams:
    topology: str                   # 'single' | 'multi' | 'buf' | 'bufmulti'
    fc_hz: float                    # -3 dB / corner frequency
    fs_hz: float                    # stopband frequency  (fs < fc for HPF)
    fs_ratio: float                 # fc_hz / fs_hz (kept for reference)
    pb_loss_db: float               # max passband insertion loss (dB)
    rolloff_dbpdec: float           # filter rolloff rate in dB/decade
    atten_db: float                 # derived stopband attenuation (dB) — always consistent
    n_stages: int                   # number of RC stages (= rolloff_dbpdec / 20)
    high_z_source: bool             # source needs buffering
    low_z_load: bool                # load needs buffering
    load_r_ohm: Optional[int]       # load resistance if low_z_load


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _log_sample_hz(lo: float, hi: float) -> float:
    """Sample a frequency on a log scale, then round to 1 significant figure."""
    v = 10 ** random.uniform(math.log10(lo), math.log10(hi))
    mag = 10 ** math.floor(math.log10(v))
    return round(v / mag) * mag


def _decades_hpf(fc_hz: float, fs_hz: float) -> float:
    """
    Number of decades between the HPF corner and its stopband.
    fc > fs for a high-pass filter, so log10(fc / fs) is positive.
    """
    return math.log10(fc_hz / fs_hz)


def _atten_from_rolloff(rolloff_dbpdec: float, fc_hz: float, fs_hz: float) -> float:
    """
    Compute the actual stopband attenuation in dB for a HPF with the given
    rolloff rate (dB/decade) at the given frequencies.

      atten_db = rolloff_dbpdec * log10(fc_hz / fs_hz)

    Rounded to one decimal place for clean prompt text.
    """
    return round(rolloff_dbpdec * _decades_hpf(fc_hz, fs_hz), 1)


# -----------------------------------------------------------------------------
# Sampler
# -----------------------------------------------------------------------------

def sample_params(
    force_high_z: Optional[bool] = None,
    force_low_z:  Optional[bool] = None,
    force_multi:  Optional[bool] = None,
) -> HPFParams:
    """
    Sample a random-but-valid set of HPF design parameters.

    Sampling order
    --------------
    1. Decide buffering (high_z / low_z).
    2. Decide whether multi-stage is required (force_multi or random).
    3. Sample rolloff_dbpdec from the appropriate set.
    4. Sample fc_hz (log-uniform) and fs_ratio -> fs_hz = fc_hz / fs_ratio.
       fs_hz < fc_hz always (stopband is below the corner for a HPF).
    5. Derive atten_db = rolloff_dbpdec * log10(fc_hz / fs_hz).
       Physically consistent by construction.
    6. Derive n_stages = rolloff_dbpdec / 20.
    7. Assign topology label.
    """
    # --- Step 1: buffering ---------------------------------------------------
    high_z = force_high_z if force_high_z is not None else (random.random() < 0.4)
    low_z  = force_low_z  if force_low_z  is not None else (random.random() < 0.35)
    buffered = high_z or low_z

    # --- Step 2: multi-stage decision ----------------------------------------
    multi = force_multi if force_multi is not None else (random.random() < 0.5)

    # --- Step 3: rolloff rate ------------------------------------------------
    if multi:
        rolloff_dbpdec = random.choice(ROLLOFF_MULTI_OPTIONS)
    else:
        rolloff_dbpdec = ROLLOFF_SINGLE_DBPDEC

    n_stages = int(round(rolloff_dbpdec / 20.0))

    # --- Step 4: frequencies -------------------------------------------------
    fc_hz    = _log_sample_hz(*FC_LOG_RANGE)
    fs_ratio = random.choice(FS_RATIO_OPTIONS)
    raw_fs   = fc_hz / fs_ratio          # HPF: stopband is BELOW the corner
    # Round to 1 significant figure so prompt frequencies are always clean numbers.
    fs_mag   = 10 ** math.floor(math.log10(raw_fs))
    fs_hz    = round(raw_fs / fs_mag) * fs_mag

    # --- Step 5: derived attenuation (always physically consistent) ----------
    atten_db = _atten_from_rolloff(rolloff_dbpdec, fc_hz, fs_hz)

    # --- Step 6: passband loss -----------------------------------------------
    pb_loss = random.choice(PB_LOSS_OPTIONS)

    # --- Step 7: load impedance ----------------------------------------------
    load_r = random.choice(LOW_Z_LOAD_OPTIONS) if (buffered and low_z) else None

    # --- Step 8: topology label ----------------------------------------------
    if not buffered and not multi:
        topo = "single"
    elif not buffered and multi:
        topo = "multi"
    elif buffered and not multi:
        topo = "buf"
    else:
        topo = "bufmulti"

    return HPFParams(
        topology=topo,
        fc_hz=fc_hz,
        fs_hz=fs_hz,
        fs_ratio=fs_ratio,
        pb_loss_db=pb_loss,
        rolloff_dbpdec=rolloff_dbpdec,
        atten_db=atten_db,
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
        s = f"{v:g}"
        return s + " kHz"
    return f"{f:g} Hz"


# -----------------------------------------------------------------------------
# Template banks  (10 variants per topology)
# -----------------------------------------------------------------------------
#
# Placeholders:
#   {fc}       - corner / passband edge frequency (formatted)  — signals ABOVE pass
#   {fs}       - stopband frequency (formatted)                — signals BELOW are blocked
#   {pb}       - passband insertion loss limit (dB, numeric)
#   {atten}    - stopband attenuation requirement (dB, numeric) — derived from rolloff
#   {load_r}   - load resistance in ohm (only for buf / bufmulti with-load banks)
#
# Templates deliberately do NOT name the topology.
# All frequency language is inverted relative to the LPF templates:
#   passband = above fc,  stopband = below fs.
# -----------------------------------------------------------------------------

TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage RC ------------------------------------------------------
    "single": [
        # 1
        "Design a high-pass filter to remove low-frequency drift from a sensor signal. "
        "Signals at {fc} and above must pass with no more than {pb} dB of attenuation. "
        "Low-frequency interference at {fs} must be reduced by at least {atten} dB. "
        "Use only resistors and capacitors, and keep the component count as small as possible.",

        # 2
        "Create a simple high-pass filter for a low-impedance signal source. "
        "The passband should begin at {fc} with less than {pb} dB insertion loss. "
        "At {fs} the circuit should provide at least {atten} dB of rejection. "
        "Minimise cost; no active components are permitted.",

        # 3
        "Specify a high-pass RC network to block low-frequency noise from a measurement line. "
        "Frequencies at {fc} and above must be passed with <= {pb} dB loss. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "The design should use the fewest passive components that satisfy these requirements.",

        # 4
        "A signal conditioning circuit is needed to remove DC offset and low-frequency hum before an ADC input. "
        "The -{pb} dB point should be at or below {fc}. "
        "Low-frequency components at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Favour the simplest possible circuit.",

        # 5
        "Design a high-pass filter for a standard-impedance signal path. "
        "Pass signals above {fc} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a high-frequency pass network to protect a downstream circuit from low-frequency interference. "
        "The insertion loss for signals above {fc} must stay below {pb} dB. "
        "At {fs}, the signal level must be reduced by at least {atten} dB. "
        "Restrict the design to resistors and capacitors; use as few as possible.",

        # 7
        "An RC high-pass filter is required for a data acquisition front end. "
        "Signals above {fc} should experience at most {pb} dB of loss. "
        "Signals at {fs} and below should be attenuated by no less than {atten} dB. "
        "The solution must be purely passive and as inexpensive as possible.",

        # 8
        "Design a high-pass filter to remove baseline wander from a signal before sampling. "
        "The passband begins at {fc} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A simple DC-blocking and low-frequency rejection filter is required. "
        "It must pass signals at {fc} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs} by at least {atten} dB. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a high-pass filter design for a general-purpose low-frequency noise rejection application. "
        "The -{pb} dB frequency should be no higher than {fc}. "
        "At {fs} the filter must deliver >= {atten} dB of attenuation. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage RC -------------------------------------------------------
    "multi": [
        # 1
        "Design a high-pass filter with a steep low-frequency roll-off for a signal conditioning application. "
        "The passband must begin at {fc} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs} must be attenuated by at least {atten} dB. "
        "Use only resistors and capacitors; minimise the total number of components.",

        # 2
        "Create a high-pass filter to strongly suppress low-frequency interference on a measurement line. "
        "Signals at {fc} and above should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection at {fs}. "
        "No active components are allowed; keep the design as cost-effective as possible.",

        # 3
        "Specify a passive high-pass RC filter for a noise-sensitive signal path. "
        "The passband edge is {fc} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Use only resistors and capacitors; use the fewest stages that meet the spec.",

        # 4
        "Design a passive high-pass filter to provide aggressive low-frequency noise rejection. "
        "Pass frequencies above {fc} with under {pb} dB loss. "
        "At {fs}, the attenuation must be at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Optimise for minimum cost.",

        # 5
        "A signal must be heavily filtered to remove low-frequency content before entering a sensitive circuit. "
        "The -{pb} dB point should be at or below {fc}. "
        "At least {atten} dB of suppression is needed at {fs}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a high-pass filter with sharp low-frequency rejection for an EMC application. "
        "Frequencies at {fc} and above must be passed with <= {pb} dB attenuation. "
        "Low-frequency interference at {fs} must be reduced by a minimum of {atten} dB. "
        "Use only resistors and capacitors, and favour the simplest topology that meets these figures.",

        # 7
        "A high-pass network is required to achieve high stopband attenuation without active components. "
        "The insertion loss must be below {pb} dB throughout the passband above {fc}. "
        "The circuit must achieve >= {atten} dB attenuation at {fs}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive high-pass filter for a data acquisition front end requiring strong low-frequency rejection. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Only R and C components; favour the lowest-cost design that meets the requirements.",

        # 9
        "Provide a high-pass filter design that achieves a high degree of low-frequency rejection using only passives. "
        "The passband begins at {fc} with a maximum of {pb} dB insertion loss. "
        "At {fs}, a minimum of {atten} dB attenuation is required. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A high-pass filter is needed with a demanding stopband specification. "
        "Frequencies at {fc} and above must be passed with <= {pb} dB loss. "
        "At {fs} the filter must attenuate signals by at least {atten} dB. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single-stage: high-Z source only (no load constraint) --------
    "buf_no_load": [
        # 1
        "Design a high-pass filter for a high-impedance signal source. "
        "The passband must begin at {fc} with no more than {pb} dB of insertion loss. "
        "At {fs}, at least {atten} dB of attenuation is required. "
        "Use resistors and capacitors, and include one op-amp if needed to handle the source impedance. "
        "Keep the circuit as simple and inexpensive as possible.",

        # 2
        "A signal from a high-impedance source must be high-pass filtered and buffered before further processing. "
        "The filter should pass frequencies at {fc} and above with <= {pb} dB attenuation. "
        "At {fs}, the rejection must be at least {atten} dB. "
        "Use passive R and C components; add one op-amp only where required by the impedance constraints.",

        # 3
        "A measurement system has a high-impedance signal source that cannot drive loads directly. "
        "A high-pass filter is required that passes {fc} with <= {pb} dB loss "
        "and attenuates {fs} by at least {atten} dB. "
        "Use one op-amp if required; otherwise use only resistors and capacitors.",

        # 4
        "Build a high-pass filter that can accept a signal from a high-impedance source. "
        "Frequencies at {fc} and above must pass with no more than {pb} dB attenuation. "
        "Frequencies at {fs} must be reduced by at least {atten} dB. "
        "Use only resistors, capacitors, and optionally one op-amp; minimise component count.",

        # 5
        "Design a high-pass filter for use with a high-impedance source that requires impedance buffering. "
        "The filter must pass signals at {fc} with <= {pb} dB insertion loss "
        "and attenuate signals at {fs} by at least {atten} dB. "
        "Use resistors and capacitors; one op-amp is allowed if it is necessary for correct operation.",

        # 6
        "Create a high-pass filter to condition a weak signal from a high-impedance transducer. "
        "Signals at {fc} and above must pass with less than {pb} dB loss. "
        "Low-frequency interference at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors, capacitors, and at most one op-amp. Minimise cost.",

        # 7
        "Specify a high-pass filter for a high-impedance sensor output. "
        "The -{pb} dB frequency must be at or below {fc}. "
        "Stopband attenuation at {fs} must reach at least {atten} dB. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 8
        "A high-impedance transducer output needs high-pass filtering before digitisation. "
        "The passband must begin at {fc} with under {pb} dB insertion loss. "
        "At {fs}, the circuit must deliver at least {atten} dB of rejection. "
        "Allow one op-amp alongside passive R and C; keep the design as simple as possible.",

        # 9
        "Provide a high-pass filter design for a high-impedance signal source. "
        "The insertion loss must be below {pb} dB from {fc} upward. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 10
        "Design a high-pass filter for a sensor with high output impedance. "
        "Signals at {fc} and above must be passed with <= {pb} dB loss. "
        "Signals at {fs} must be attenuated by at least {atten} dB. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum part count.",
    ],

    # -- Buffered single-stage: high-Z source + explicit low-Z load ------------
    "buf_with_load": [
        # 1
        "Create a high-pass filter to condition a weak signal from a high-impedance transducer "
        "and drive a {load_r} ohm load. "
        "Signals at {fc} and above must pass with less than {pb} dB loss. "
        "Low-frequency interference at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors, capacitors, and at most one op-amp.",

        # 2
        "Specify a high-pass filter for a high-impedance sensor output feeding a {load_r} ohm load. "
        "The -{pb} dB frequency must be at or below {fc}. "
        "Stopband attenuation at {fs} must reach at least {atten} dB. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 3
        "Design a high-pass filter to interface a high-impedance source to a {load_r} ohm downstream circuit. "
        "Pass signals at {fc} and above with under {pb} dB insertion loss. "
        "Provide >= {atten} dB of rejection at {fs}. "
        "Components are limited to resistors, capacitors, and one op-amp if needed. Minimise cost.",

        # 4
        "Design a high-pass filter for a sensor interface where the source impedance is high "
        "and the load is {load_r} ohm. "
        "The passband must begin at {fc} with less than {pb} dB loss. "
        "At {fs}, at least {atten} dB of suppression is needed. "
        "Allow resistors, capacitors, and at most one op-amp; keep the design simple.",

        # 5
        "Provide a high-pass filter design for a high-impedance signal source driving a {load_r} ohm load. "
        "The insertion loss must be below {pb} dB from {fc} upward. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 6
        "A high-impedance sensor feeds a {load_r} ohm input stage. "
        "Design a high-pass filter between them that passes {fc} with <= {pb} dB loss "
        "and rejects {fs} by at least {atten} dB. "
        "Use resistors, capacitors, and one op-amp if necessary; minimise component count.",

        # 7
        "Design a high-pass filter for a high-impedance signal source whose output "
        "must drive a {load_r} ohm load without attenuation of in-band signals. "
        "The passband edge is {fc} with <= {pb} dB insertion loss. "
        "At {fs}, at least {atten} dB of rejection is required. "
        "Use R, C, and at most one op-amp; optimise for low cost.",

        # 8
        "A weak, high-impedance signal must be high-pass filtered and presented to a {load_r} ohm load. "
        "The filter must pass {fc} with less than {pb} dB loss "
        "and suppress {fs} by at least {atten} dB. "
        "Allow one op-amp if needed; otherwise restrict to passive components.",

        # 9
        "Specify a high-pass filter to buffer a high-impedance source and drive a {load_r} ohm load. "
        "Signals at {fc} and above must be passed with <= {pb} dB attenuation. "
        "At {fs}, the attenuation must be at least {atten} dB. "
        "Use resistors, capacitors, and optionally one op-amp; favour the simplest design.",

        # 10
        "Build a high-pass filter for a high-impedance sensor output connected to a {load_r} ohm input. "
        "The circuit must pass {fc} with under {pb} dB insertion loss "
        "and deliver >= {atten} dB rejection at {fs}. "
        "Permitted parts: R, C, and one op-amp if required. Keep BOM cost minimal.",
    ],

    # -- Buffered multi-stage: high-Z source only (no load constraint) ---------
    "bufmulti_no_load": [
        # 1
        "Design a high-pass filter for a high-impedance signal source requiring high stopband attenuation. "
        "The passband must begin at {fc} with no more than {pb} dB insertion loss. "
        "At {fs}, at least {atten} dB of attenuation is required. "
        "Use resistors, capacitors, and at most one op-amp. Minimise cost and component count.",

        # 2
        "A high-impedance transducer feeds a high-pass filter that must deliver strong low-frequency rejection. "
        "Frequencies at {fc} and above must be passed with <= {pb} dB attenuation. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "Use resistors, capacitors, and at most one op-amp; use the fewest stages that meet the specification.",

        # 3
        "Design a high-pass filter with aggressive low-frequency noise rejection for a high-impedance sensor interface. "
        "The passband must begin at {fc} with under {pb} dB loss. "
        "Provide >= {atten} dB of rejection at {fs}. "
        "An op-amp is permitted to handle source impedance; use only passive components otherwise.",

        # 4
        "Design a high-pass filter for a high-impedance signal source with demanding stopband requirements. "
        "Frequencies at {fc} and above must be passed with less than {pb} dB loss. "
        "At {fs}, the filter must deliver at least {atten} dB of attenuation. "
        "Restrict components to resistors, capacitors, and at most one op-amp; minimise part count.",

        # 5
        "Provide a high-pass filter design for a high-impedance source that requires both "
        "impedance buffering and steep low-frequency roll-off. "
        "The insertion loss must be below {pb} dB throughout the passband above {fc}. "
        "At {fs}, at least {atten} dB of attenuation is required. "
        "Use resistors, capacitors, and one op-amp; minimise the total number of components.",

        # 6
        "A high-impedance sensor signal requires heavy high-pass filtering before digitisation. "
        "Signals at {fc} and above must pass with <= {pb} dB loss. "
        "Signals at {fs} must be attenuated by at least {atten} dB. "
        "Allow one op-amp to buffer the source; keep remaining components passive (R and C only).",

        # 7
        "Specify a high-pass filter for a high-impedance source with a sharp stopband-to-passband transition. "
        "The -{pb} dB point must be at or below {fc}. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum BOM cost.",

        # 8
        "Design a steep-roll-off high-pass filter for a weak, high-impedance signal. "
        "Passband loss must not exceed {pb} dB above {fc}. "
        "Stopband attenuation at {fs} must be at least {atten} dB. "
        "Use R, C, and one op-amp if necessary; keep the design as low-cost as possible.",

        # 9
        "Create a high-pass filter for a high-impedance transducer requiring strong out-of-band rejection. "
        "Signals at {fc} must pass with less than {pb} dB insertion loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors, capacitors, and one op-amp. Minimise component count.",

        # 10
        "A high-impedance source drives a high-pass filter that must achieve aggressive low-frequency attenuation. "
        "The passband edge is {fc} with <= {pb} dB loss. "
        "At {fs}, the circuit must deliver >= {atten} dB of attenuation. "
        "Use resistors, capacitors, and at most one op-amp; favour the simplest design that meets the spec.",
    ],

    # -- Buffered multi-stage: high-Z source + explicit low-Z load -------------
    "bufmulti_with_load": [
        # 1
        "Create a high-pass filter to condition a weak, high-impedance signal and drive a {load_r} ohm load. "
        "Signals at {fc} and above must pass with less than {pb} dB loss. "
        "Frequencies at {fs} must be suppressed by at least {atten} dB. "
        "Allow one op-amp if necessary; otherwise restrict to passive R and C components.",

        # 2
        "Specify a high-pass filter for a high-impedance source driving a {load_r} ohm load. "
        "The -{pb} dB frequency must be at or below {fc}. "
        "Stopband rejection at {fs} must be at least {atten} dB. "
        "Components: resistors, capacitors, and one op-amp if required. Optimise for minimum BOM cost.",

        # 3
        "A signal chain begins at a high-impedance source and must drive a {load_r} ohm load after filtering. "
        "The high-pass filter must pass {fc} with <= {pb} dB insertion loss "
        "and suppress {fs} by at least {atten} dB. "
        "Use one op-amp if needed; keep all other components passive (R and C only).",

        # 4
        "Build a high-pass filter to interface a high-impedance sensor to a {load_r} ohm load. "
        "The passband edge is {fc}; insertion loss must be below {pb} dB above this frequency. "
        "A minimum of {atten} dB suppression is needed at {fs}. "
        "Permitted components: R, C, and one op-amp if necessary. Keep the design as low-cost as possible.",

        # 5
        "Design a high-pass filter for a high-impedance signal source driving a {load_r} ohm load, "
        "with a sharp transition from stopband to passband. "
        "Signals at {fc} must pass with <= {pb} dB loss. "
        "Signals at {fs} must be attenuated by at least {atten} dB. "
        "Allow one op-amp alongside passive R and C components; optimise for simplicity and low cost.",

        # 6
        "A high-impedance sensor output must drive a {load_r} ohm load through a steep high-pass filter. "
        "Pass frequencies at {fc} and above with <= {pb} dB loss. "
        "Reject frequencies at {fs} by at least {atten} dB. "
        "Use resistors, capacitors, and one op-amp; minimise total component count.",

        # 7
        "Specify a high-pass filter for a high-impedance source whose output feeds a {load_r} ohm stage. "
        "The passband must begin at {fc} with less than {pb} dB insertion loss. "
        "At {fs}, the filter must deliver at least {atten} dB of attenuation. "
        "Restrict to R, C, and at most one op-amp; favour the lowest-cost design.",

        # 8
        "Design a steep-roll-off high-pass filter for a high-impedance sensor driving a {load_r} ohm load. "
        "The -{pb} dB frequency must be at or below {fc}. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Allow one op-amp to buffer the source; otherwise use only passive components.",

        # 9
        "A weak signal from a high-impedance source must be filtered and presented to a {load_r} ohm input. "
        "Signals at {fc} and above must pass with <= {pb} dB attenuation. "
        "At {fs}, the suppression must be at least {atten} dB. "
        "Use R, C, and one op-amp if necessary; keep the design as inexpensive as possible.",

        # 10
        "Create a high-attenuation high-pass filter for a high-impedance transducer feeding a {load_r} ohm load. "
        "Passband loss must be below {pb} dB above {fc}. "
        "Stopband attenuation at {fs} must reach at least {atten} dB. "
        "Permitted parts: resistors, capacitors, and at most one op-amp. Minimise BOM cost.",
    ],
}


# -----------------------------------------------------------------------------
# SPICE output-format post-amble (appended to every prompt)
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

def generate_hpf_prompt(
    params: Optional[HPFParams] = None,
    template_index: Optional[int] = None,
) -> dict:
    """
    Generate a single HPF design prompt.

    Parameters
    ----------
    params : HPFParams, optional
        Pre-sampled parameters. If None, parameters are sampled randomly.
    template_index : int, optional
        0-based index into the template list for the selected topology.
        If None, a template is chosen at random.

    Returns
    -------
    dict with keys:
        prompt       - the complete prompt string (body + SPICE post-amble)
        task_type    - 'high_pass_filter'
        topology     - ground-truth topology label
        params       - the HPFParams used (as a dict)
        template_i   - which template variant was used (0-based)
    """
    if params is None:
        params = sample_params()

    # Resolve buf/bufmulti to the correct sub-bank based on whether a
    # load impedance was actually sampled.
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

    template = bank[template_index]

    body = template.format(
        fc=_fmt_hz(params.fc_hz),
        fs=_fmt_hz(params.fs_hz),
        pb=params.pb_loss_db,
        atten=params.atten_db,
        load_r=params.load_r_ohm,
    )

    prompt = body + SPICE_POSTAMBLE

    return {
        "prompt": prompt,
        "task_type": "high_pass_filter",
        "topology": params.topology,
        "params": asdict(params),
        "template_i": template_index,
    }


def generate_dataset(
    n: int = 100,
    seed: Optional[int] = None,
    balanced: bool = True,
) -> list[dict]:
    """
    Generate a dataset of n HPF prompts.

    Parameters
    ----------
    n       : total number of prompts to generate
    seed    : random seed for reproducibility
    balanced: if True, each topology gets roughly equal representation

    Returns
    -------
    List of prompt dicts (see generate_hpf_prompt for schema).
    """
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
            results.append(generate_hpf_prompt(params=p))
    else:
        for _ in range(n):
            results.append(generate_hpf_prompt())

    random.shuffle(results)
    return results


# -----------------------------------------------------------------------------
# Quick demo / CLI
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed_val  = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    print(f"Generating {n_samples} balanced HPF prompts (seed={seed_val})\n")
    print("=" * 72)

    dataset = generate_dataset(n=n_samples, seed=seed_val, balanced=True)

    for i, item in enumerate(dataset, 1):
        p = item["params"]
        decades = _decades_hpf(p["fc_hz"], p["fs_hz"])
        print(f"\n[{i}/{n_samples}]  topology={item['topology'].upper():<10} "
              f"template={item['template_i']}  "
              f"fs={_fmt_hz(p['fs_hz'])}  "
              f"fc={_fmt_hz(p['fc_hz'])}  "
              f"rolloff={p['rolloff_dbpdec']} dB/dec  "
              f"decades={decades:.3f}  "
              f"atten={p['atten_db']} dB  "
              f"n_stages={p['n_stages']}")
        print("-" * 72)
        print(item["prompt"])
        print("=" * 72)

    # Optionally dump JSON
    out_path = "hpf_dataset.json"
    with open(out_path, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"\nDataset written to {out_path}")
