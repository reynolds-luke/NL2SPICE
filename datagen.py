"""
lpf_prompt_generator.py
=======================
Generates natural-language design prompts for low-pass filter circuits.
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
  multi     = stopband_attenuation_db > MULTI_THRESHOLD_DB   (default 20 dB)
  ->  single    : not buffered, not multi
  ->  multi     : not buffered, multi
  ->  buf       : buffered, not multi
  ->  bufmulti  : buffered, multi

SPICE node convention (enforced in every prompt via the post-amble)
-------------------------------------------------------------------
  VIN   - input node
  VOUT  - output node
  GND   - ground / reference node (0 V)
"""

import random
import math
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

MULTI_THRESHOLD_DB: float = 20.0   # attenuation above this -> multi-stage

# Attenuation buckets: (min_db, max_db, step_db)
ATTEN_SINGLE   = (10, 20, 1)
ATTEN_MULTI    = (25, 50, 5)

# Corner frequency range (Hz) - sampled on log scale
FC_LOG_RANGE = (100, 100_000)

# Stopband frequency ratio relative to corner (fs = fc * ratio)
FS_RATIO_OPTIONS = [2, 3, 4, 5, 10]

# Passband ripple options (dB)
PB_LOSS_OPTIONS = [0.5, 1.0, 1.0, 1.0, 2.0, 3.0]   # weighted towards 1 dB

# Load impedances used in low-Z scenarios
LOW_Z_LOAD_OPTIONS = [500, 1_000, 1_500, 2_000, 4_700]


# -----------------------------------------------------------------------------
# Parameter dataclass
# -----------------------------------------------------------------------------

@dataclass
class LPFParams:
    topology: str                   # 'single' | 'multi' | 'buf' | 'bufmulti'
    fc_hz: float                    # -3 dB / corner frequency
    fs_hz: float                    # stopband frequency
    pb_loss_db: float               # max passband insertion loss (dB)
    atten_db: float                 # min stopband attenuation (dB)
    high_z_source: bool             # source needs buffering
    low_z_load: bool                # load needs buffering
    load_r_ohm: Optional[int]       # load resistance if low_z_load


# -----------------------------------------------------------------------------
# Samplers
# -----------------------------------------------------------------------------

def _log_sample_hz(lo: float, hi: float) -> float:
    """Sample a frequency on a log scale, then round to 1 significant figure."""
    v = 10 ** random.uniform(math.log10(lo), math.log10(hi))
    mag = 10 ** math.floor(math.log10(v))
    return round(v / mag) * mag


def _sample_atten(multi: bool) -> float:
    lo, hi, step = ATTEN_MULTI if multi else ATTEN_SINGLE
    return random.randrange(lo, hi + 1, step)


def sample_params(
    force_high_z: Optional[bool] = None,
    force_low_z:  Optional[bool] = None,
    force_multi:  Optional[bool] = None,
) -> LPFParams:
    """
    Sample a random-but-valid set of LPF design parameters.
    Optional overrides allow forcing a specific topology dimension.
    """
    high_z = force_high_z if force_high_z is not None else (random.random() < 0.4)
    low_z  = force_low_z  if force_low_z  is not None else (random.random() < 0.35)
    buffered = high_z or low_z

    multi_forced = (
        force_multi if force_multi is not None
        else (random.random() < 0.5)
    )
    atten = _sample_atten(multi=multi_forced)
    multi = atten > MULTI_THRESHOLD_DB

    fc  = _log_sample_hz(*FC_LOG_RANGE)
    fs  = fc * random.choice(FS_RATIO_OPTIONS)

    pb_loss  = random.choice(PB_LOSS_OPTIONS)
    load_r   = random.choice(LOW_Z_LOAD_OPTIONS) if (buffered and low_z) else None

    if not buffered and not multi:
        topo = "single"
    elif not buffered and multi:
        topo = "multi"
    elif buffered and not multi:
        topo = "buf"
    else:
        topo = "bufmulti"

    return LPFParams(
        topology=topo,
        fc_hz=fc,
        fs_hz=fs,
        pb_loss_db=pb_loss,
        atten_db=atten,
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
#   {fc}       - corner / passband frequency (formatted)
#   {fs}       - stopband frequency (formatted)
#   {pb}       - passband insertion loss limit (dB, numeric)
#   {atten}    - stopband attenuation requirement (dB, numeric)
#   {load_r}   - load resistance in ohm (only for buf / bufmulti)
#
# Templates deliberately do NOT name the topology.
# -----------------------------------------------------------------------------

TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage RC ------------------------------------------------------
    "single": [
        # 1
        "Design a low-pass filter to clean up a sensor signal. "
        "Signals at {fc} and below must pass with no more than {pb} dB of attenuation. "
        "Interference at {fs} must be reduced by at least {atten} dB. "
        "Use only resistors and capacitors, and keep the component count as small as possible.",

        # 2
        "Create a simple low-pass filter for a low-impedance signal source. "
        "The passband should extend to {fc} with less than {pb} dB insertion loss. "
        "At {fs} the circuit should provide at least {atten} dB of rejection. "
        "Minimise cost; no active components are permitted.",

        # 3
        "Specify a low-pass RC network to remove high-frequency noise from a measurement line. "
        "Frequencies up to {fc} must be passed with <= {pb} dB loss. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "The design should use the fewest passive components that satisfy these requirements.",

        # 4
        "A signal conditioning circuit is needed to limit bandwidth before an ADC input. "
        "The -{pb} dB point should be at or above {fc}. "
        "Noise components at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Favour the simplest possible circuit.",

        # 5
        "Design a low-pass filter for a standard-impedance signal path. "
        "Pass signals through {fc} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a low-frequency pass network to protect a downstream circuit from high-frequency interference. "
        "The insertion loss in the passband up to {fc} must stay below {pb} dB. "
        "At {fs}, the signal level must be reduced by at least {atten} dB. "
        "Restrict the design to resistors and capacitors; use as few as possible.",

        # 7
        "An RC low-pass filter is required for a data acquisition front end. "
        "Signals below {fc} should experience at most {pb} dB of loss. "
        "Signals at {fs} and above should be attenuated by no less than {atten} dB. "
        "The solution must be purely passive and as inexpensive as possible.",

        # 8
        "Design a low-pass filter to band-limit a signal before sampling. "
        "The passband extends to {fc} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A simple anti-aliasing filter is required. "
        "It must pass signals at {fc} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs} by at least {atten} dB. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a low-pass filter design for a general-purpose noise-reduction application. "
        "The -{pb} dB frequency should be no lower than {fc}. "
        "At {fs} the filter must deliver >= {atten} dB of attenuation. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage RC -------------------------------------------------------
    "multi": [
        # 1
        "Design a low-pass filter with a steep roll-off for a signal conditioning application. "
        "The passband must extend to {fc} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs} must be attenuated by at least {atten} dB. "
        "Use only resistors and capacitors; minimise the total number of components.",

        # 2
        "Create a low-pass filter to strongly suppress high-frequency interference on a measurement line. "
        "Signals up to {fc} should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection at {fs}. "
        "No active components are allowed; keep the design as cost-effective as possible.",

        # 3
        "Specify a passive low-pass RC filter for a noise-sensitive signal path. "
        "The passband edge is {fc} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Use only resistors and capacitors; use the fewest stages that meet the spec.",

        # 4
        "Design a passive low-pass filter to provide aggressive noise rejection. "
        "Pass frequencies below {fc} with under {pb} dB loss. "
        "At {fs}, the attenuation must be at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Optimise for minimum cost.",

        # 5
        "A signal must be heavily filtered before entering a sensitive measurement circuit. "
        "The -{pb} dB point should be at or above {fc}. "
        "At least {atten} dB of suppression is needed at {fs}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a low-pass filter with sharp high-frequency rejection for an EMC application. "
        "Frequencies up to {fc} must be passed with <= {pb} dB attenuation. "
        "Interference at {fs} must be reduced by a minimum of {atten} dB. "
        "Use only resistors and capacitors, and favour the simplest topology that meets these figures.",

        # 7
        "A low-pass network is required to achieve high stopband attenuation without active components. "
        "The insertion loss must be below {pb} dB throughout the passband up to {fc}. "
        "The circuit must achieve >= {atten} dB attenuation at {fs}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive low-pass filter for a data acquisition front end requiring strong alias rejection. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Only R and C components; favour the lowest-cost design that meets the requirements.",

        # 9
        "Provide a low-pass filter design that achieves a high degree of noise rejection using only passives. "
        "The passband extends to {fc} with a maximum of {pb} dB insertion loss. "
        "At {fs}, a minimum of {atten} dB attenuation is required. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A low-pass filter is needed with a demanding stopband specification. "
        "Frequencies up to {fc} must be passed with <= {pb} dB loss. "
        "At {fs} the filter must attenuate signals by at least {atten} dB. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single-stage: high-Z source only (no load constraint) ----------
    "buf_no_load": [
        # 1
        "Design a low-pass filter for a high-impedance signal source. "
        "The passband must extend to {fc} with no more than {pb} dB of insertion loss. "
        "At {fs}, at least {atten} dB of attenuation is required. "
        "Use resistors and capacitors, and include one op-amp if needed to handle the source impedance. "
        "Keep the circuit as simple and inexpensive as possible.",

        # 2
        "A signal from a high-impedance source must be filtered and buffered before further processing. "
        "The filter should pass frequencies up to {fc} with <= {pb} dB attenuation. "
        "At {fs}, the rejection must be at least {atten} dB. "
        "Use passive R and C components; add one op-amp only where required by the impedance constraints.",

        # 3
        "A measurement system has a high-impedance signal source that cannot drive loads directly. "
        "A low-pass filter is required that passes {fc} with <= {pb} dB loss "
        "and attenuates {fs} by at least {atten} dB. "
        "Use one op-amp if required; otherwise use only resistors and capacitors.",

        # 4
        "Build a low-pass filter that can accept a signal from a high-impedance source. "
        "Frequencies up to {fc} must pass with no more than {pb} dB attenuation. "
        "Frequencies at {fs} must be reduced by at least {atten} dB. "
        "Use only resistors, capacitors, and optionally one op-amp; minimise component count.",

        # 5
        "Design a low-pass filter for use with a high-impedance source that requires impedance buffering. "
        "The filter must pass signals at {fc} with <= {pb} dB insertion loss "
        "and attenuate signals at {fs} by at least {atten} dB. "
        "Use resistors and capacitors; one op-amp is allowed if it is necessary for correct operation.",

        # 6
        "Create a low-pass filter to condition a weak signal from a high-impedance transducer. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Interference at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors, capacitors, and at most one op-amp. Minimise cost.",

        # 7
        "Specify a low-pass filter for a high-impedance sensor output. "
        "The -{pb} dB frequency must be at or above {fc}. "
        "Stopband attenuation at {fs} must reach at least {atten} dB. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 8
        "A high-impedance transducer output needs low-pass filtering before digitisation. "
        "The passband must reach {fc} with under {pb} dB insertion loss. "
        "At {fs}, the circuit must deliver at least {atten} dB of rejection. "
        "Allow one op-amp alongside passive R and C; keep the design as simple as possible.",

        # 9
        "Provide a low-pass filter design for a high-impedance signal source. "
        "The insertion loss must be below {pb} dB up to {fc}. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 10
        "Design a low-pass filter for a sensor with high output impedance. "
        "Signals at {fc} and below must be passed with <= {pb} dB loss. "
        "Signals at {fs} must be attenuated by at least {atten} dB. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum part count.",
    ],

    # -- Buffered single-stage: high-Z source + explicit low-Z load ------------
    "buf_with_load": [
        # 1
        "Create a low-pass filter to condition a weak signal from a high-impedance transducer "
        "and drive a {load_r} ohm load. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Interference at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors, capacitors, and at most one op-amp.",

        # 2
        "Specify a low-pass filter for a high-impedance sensor output feeding a {load_r} ohm load. "
        "The -{pb} dB frequency must be at or above {fc}. "
        "Stopband attenuation at {fs} must reach at least {atten} dB. "
        "Use the minimum number of components; an op-amp is permitted if necessary.",

        # 3
        "Design a low-pass filter to interface a high-impedance source to a {load_r} ohm downstream circuit. "
        "Pass signals at {fc} with under {pb} dB insertion loss. "
        "Provide >= {atten} dB of rejection at {fs}. "
        "Components are limited to resistors, capacitors, and one op-amp if needed. Minimise cost.",

        # 4
        "Design a low-pass filter for a sensor interface where the source impedance is high "
        "and the load is {load_r} ohm. "
        "The passband must extend to {fc} with less than {pb} dB loss. "
        "At {fs}, at least {atten} dB of suppression is needed. "
        "Allow resistors, capacitors, and at most one op-amp; keep the design simple.",

        # 5
        "Provide a low-pass filter design for a high-impedance signal source driving a {load_r} ohm load. "
        "The insertion loss must be below {pb} dB up to {fc}. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Only one op-amp is permitted alongside resistors and capacitors; keep the BOM cost low.",

        # 6
        "A high-impedance sensor feeds a {load_r} ohm input stage. "
        "Design a low-pass filter between them that passes {fc} with <= {pb} dB loss "
        "and rejects {fs} by at least {atten} dB. "
        "Use resistors, capacitors, and one op-amp if necessary; minimise component count.",

        # 7
        "Design a low-pass filter for a high-impedance signal source whose output "
        "must drive a {load_r} ohm load without attenuation. "
        "The passband edge is {fc} with <= {pb} dB insertion loss. "
        "At {fs}, at least {atten} dB of rejection is required. "
        "Use R, C, and at most one op-amp; optimise for low cost.",

        # 8
        "A weak, high-impedance signal must be filtered and presented to a {load_r} ohm load. "
        "The filter must pass {fc} with less than {pb} dB loss "
        "and suppress {fs} by at least {atten} dB. "
        "Allow one op-amp if needed; otherwise restrict to passive components.",

        # 9
        "Specify a low-pass filter to buffer a high-impedance source and drive a {load_r} ohm load. "
        "Signals up to {fc} must be passed with <= {pb} dB attenuation. "
        "At {fs}, the attenuation must be at least {atten} dB. "
        "Use resistors, capacitors, and optionally one op-amp; favour the simplest design.",

        # 10
        "Build a low-pass filter for a high-impedance sensor output connected to a {load_r} ohm input. "
        "The circuit must pass {fc} with under {pb} dB insertion loss "
        "and deliver >= {atten} dB rejection at {fs}. "
        "Permitted parts: R, C, and one op-amp if required. Keep BOM cost minimal.",
    ],

    # -- Buffered multi-stage: high-Z source only (no load constraint) ---------
    "bufmulti_no_load": [
        # 1
        "Design a low-pass filter for a high-impedance signal source requiring high stopband attenuation. "
        "The passband must reach {fc} with no more than {pb} dB insertion loss. "
        "At {fs}, at least {atten} dB of attenuation is required. "
        "Use resistors, capacitors, and at most one op-amp. Minimise cost and component count.",

        # 2
        "A high-impedance transducer feeds a low-pass filter that must deliver strong high-frequency rejection. "
        "Frequencies up to {fc} must be passed with <= {pb} dB attenuation. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "Use resistors, capacitors, and at most one op-amp; use the fewest stages that meet the specification.",

        # 3
        "Design a low-pass filter with aggressive noise rejection for a high-impedance sensor interface. "
        "The passband must extend to {fc} with under {pb} dB loss. "
        "Provide >= {atten} dB of rejection at {fs}. "
        "An op-amp is permitted to handle source impedance; use only passive components otherwise.",

        # 4
        "Design a low-pass filter for a high-impedance signal source with demanding stopband requirements. "
        "Frequencies at {fc} and below must be passed with less than {pb} dB loss. "
        "At {fs}, the filter must deliver at least {atten} dB of attenuation. "
        "Restrict components to resistors, capacitors, and at most one op-amp; minimise part count.",

        # 5
        "Provide a low-pass filter design for a high-impedance source that requires both "
        "impedance buffering and steep roll-off. "
        "The insertion loss must be below {pb} dB throughout the passband up to {fc}. "
        "At {fs}, at least {atten} dB of attenuation is required. "
        "Use resistors, capacitors, and one op-amp; minimise the total number of components.",

        # 6
        "A high-impedance sensor signal requires heavy low-pass filtering before digitisation. "
        "Signals up to {fc} must pass with <= {pb} dB loss. "
        "Signals at {fs} must be attenuated by at least {atten} dB. "
        "Allow one op-amp to buffer the source; keep remaining components passive (R and C only).",

        # 7
        "Specify a low-pass filter for a high-impedance source with a sharp passband-to-stopband transition. "
        "The -{pb} dB point must be at or above {fc}. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Use resistors, capacitors, and at most one op-amp; optimise for minimum BOM cost.",

        # 8
        "Design a steep-roll-off low-pass filter for a weak, high-impedance signal. "
        "Passband loss must not exceed {pb} dB at {fc}. "
        "Stopband attenuation at {fs} must be at least {atten} dB. "
        "Use R, C, and one op-amp if necessary; keep the design as low-cost as possible.",

        # 9
        "Create a low-pass filter for a high-impedance transducer requiring strong out-of-band rejection. "
        "Signals at {fc} must pass with less than {pb} dB insertion loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors, capacitors, and one op-amp. Minimise component count.",

        # 10
        "A high-impedance source drives a low-pass filter that must achieve aggressive stopband attenuation. "
        "The passband edge is {fc} with <= {pb} dB loss. "
        "At {fs}, the circuit must deliver >= {atten} dB of attenuation. "
        "Use resistors, capacitors, and at most one op-amp; favour the simplest design that meets the spec.",
    ],

    # -- Buffered multi-stage: high-Z source + explicit low-Z load -------------
    "bufmulti_with_load": [
        # 1
        "Create a low-pass filter to condition a weak, high-impedance signal and drive a {load_r} ohm load. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Frequencies at {fs} must be suppressed by at least {atten} dB. "
        "Allow one op-amp if necessary; otherwise restrict to passive R and C components.",

        # 2
        "Specify a low-pass filter for a high-impedance source driving a {load_r} ohm load. "
        "The -{pb} dB frequency must be at or above {fc}. "
        "Stopband rejection at {fs} must be at least {atten} dB. "
        "Components: resistors, capacitors, and one op-amp if required. Optimise for minimum BOM cost.",

        # 3
        "A signal chain begins at a high-impedance source and must drive a {load_r} ohm load after filtering. "
        "The low-pass filter must pass {fc} with <= {pb} dB insertion loss "
        "and suppress {fs} by at least {atten} dB. "
        "Use one op-amp if needed; keep all other components passive (R and C only).",

        # 4
        "Build a low-pass filter to interface a high-impedance sensor to a {load_r} ohm load. "
        "The passband edge is {fc}; insertion loss must be below {pb} dB in the passband. "
        "A minimum of {atten} dB suppression is needed at {fs}. "
        "Permitted components: R, C, and one op-amp if necessary. Keep the design as low-cost as possible.",

        # 5
        "Design a low-pass filter for a high-impedance signal source driving a {load_r} ohm load, "
        "with a sharp transition from passband to stopband. "
        "Signals at {fc} must pass with <= {pb} dB loss. "
        "Signals at {fs} must be attenuated by at least {atten} dB. "
        "Allow one op-amp alongside passive R and C components; optimise for simplicity and low cost.",

        # 6
        "A high-impedance sensor output must drive a {load_r} ohm load through a steep low-pass filter. "
        "Pass frequencies up to {fc} with <= {pb} dB loss. "
        "Reject frequencies at {fs} by at least {atten} dB. "
        "Use resistors, capacitors, and one op-amp; minimise total component count.",

        # 7
        "Specify a low-pass filter for a high-impedance source whose output feeds a {load_r} ohm stage. "
        "The passband must extend to {fc} with less than {pb} dB insertion loss. "
        "At {fs}, the filter must deliver at least {atten} dB of attenuation. "
        "Restrict to R, C, and at most one op-amp; favour the lowest-cost design.",

        # 8
        "Design a steep-roll-off low-pass filter for a high-impedance sensor driving a {load_r} ohm load. "
        "The -{pb} dB frequency must be at or above {fc}. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Allow one op-amp to buffer the source; otherwise use only passive components.",

        # 9
        "A weak signal from a high-impedance source must be filtered and presented to a {load_r} ohm input. "
        "Signals up to {fc} must pass with <= {pb} dB attenuation. "
        "At {fs}, the suppression must be at least {atten} dB. "
        "Use R, C, and one op-amp if necessary; keep the design as inexpensive as possible.",

        # 10
        "Create a high-attenuation low-pass filter for a high-impedance transducer feeding a {load_r} ohm load. "
        "Passband loss must be below {pb} dB at {fc}. "
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

def generate_lpf_prompt(
    params: Optional[LPFParams] = None,
    template_index: Optional[int] = None,
) -> dict:
    """
    Generate a single LPF design prompt.

    Parameters
    ----------
    params : LPFParams, optional
        Pre-sampled parameters. If None, parameters are sampled randomly.
    template_index : int, optional
        0-based index into the template list for the selected topology.
        If None, a template is chosen at random.

    Returns
    -------
    dict with keys:
        prompt     - the complete prompt string (body + SPICE post-amble)
        topology   - ground-truth topology label
        params     - the LPFParams used (as a dict)
        template_i - which template variant was used (0-based)
    """
    if params is None:
        params = sample_params()

    # Resolve buf/bufmulti to the correct sub-bank based on whether a
    # load impedance was actually sampled.  This prevents {load_r} from
    # ever appearing in a prompt when no load value exists.
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

    # Fill placeholders ({load_r} only appears in *_with_load banks)
    body = template.format(
        fc=_fmt_hz(params.fc_hz),
        fs=_fmt_hz(params.fs_hz),
        pb=params.pb_loss_db,
        atten=int(params.atten_db),
        load_r=params.load_r_ohm,
    )

    prompt = body + SPICE_POSTAMBLE

    return {
        "prompt": prompt,
        "task_type": "low_pass_filter",
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
    Generate a dataset of n LPF prompts.

    Parameters
    ----------
    n       : total number of prompts to generate
    seed    : random seed for reproducibility
    balanced: if True, each topology gets roughly equal representation

    Returns
    -------
    List of prompt dicts (see generate_lpf_prompt for schema).
    """
    if seed is not None:
        random.seed(seed)

    results = []

    if balanced:
        topos = ["single", "multi", "buf", "bufmulti"]
        flags = {
            "single":   dict(force_high_z=False, force_low_z=False, force_multi=False),
            "multi":    dict(force_high_z=False, force_low_z=False, force_multi=True),
            # For buffered topologies, leave force_low_z=None so the sampler
            # randomly decides whether a load impedance is present.  This
            # exercises both *_with_load and *_no_load template sub-banks.
            "buf":      dict(force_high_z=True,  force_low_z=None,  force_multi=False),
            "bufmulti": dict(force_high_z=True,  force_low_z=None,  force_multi=True),
        }
        for i in range(n):
            topo = topos[i % len(topos)]
            p = sample_params(**flags[topo])
            results.append(generate_lpf_prompt(params=p))
    else:
        for _ in range(n):
            results.append(generate_lpf_prompt())

    random.shuffle(results)
    return results


# -----------------------------------------------------------------------------
# Quick demo / CLI
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    seed_val  = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    print(f"Generating {n_samples} balanced LPF prompts (seed={seed_val})\n")
    print("=" * 72)

    dataset = generate_dataset(n=n_samples, seed=seed_val, balanced=True)

    for i, item in enumerate(dataset, 1):
        p = item["params"]
        print(f"\n[{i}/{n_samples}]  topology={item['topology'].upper():<10} "
              f"template={item['template_i']}  "
              f"fc={_fmt_hz(p['fc_hz'])}  "
              f"fs={_fmt_hz(p['fs_hz'])}  "
              f"atten={int(p['atten_db'])} dB")
        print("-" * 72)
        print(item["prompt"])
        print("=" * 72)

    # Optionally dump JSON
    out_path = "lpf_dataset.json"
    with open(out_path, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"\nDataset written to {out_path}")