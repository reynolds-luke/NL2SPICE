TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage RC ------------------------------------------------------
    "rc_single": [
        # 1
        "Design a high-pass filter to clean up a sensor signal. "
        "Signals at {fc} and above must pass with no more than {pb} dB of attenuation. "
        "Interference at {fs} must be reduced by at least {atten} dB. "
        "Use only resistors and capacitors, and keep the component count as small as possible.",

        # 2
        "Create a simple high-pass filter for a low-impedance signal source. "
        "The passband should extend from {fc} with less than {pb} dB insertion loss. "
        "At {fs} the circuit should provide at least {atten} dB of rejection. "
        "Minimise cost; no active components are permitted.",

        # 3
        "Specify a high-pass RC network to remove low-frequency noise from a measurement line. "
        "Frequencies from {fc} upward must be passed with <= {pb} dB loss. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "The design should use the fewest passive components that satisfy these requirements.",

        # 4
        "A signal conditioning circuit is needed to block DC and low-frequency content before an ADC input. "
        "The -{pb} dB point should be at or below {fc}. "
        "Low-frequency components at {fs} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Favour the simplest possible circuit.",

        # 5
        "Design a high-pass filter for a standard-impedance signal path. "
        "Pass signals from {fc} upward with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a high-frequency pass network to protect a downstream circuit from low-frequency interference. "
        "The insertion loss in the passband from {fc} upward must stay below {pb} dB. "
        "At {fs}, the signal level must be reduced by at least {atten} dB. "
        "Restrict the design to resistors and capacitors; use as few as possible.",

        # 7
        "A high-pass RC filter is required for a data acquisition front end. "
        "Signals above {fc} should experience at most {pb} dB of loss. "
        "Signals at {fs} and below should be attenuated by no less than {atten} dB. "
        "The solution must be purely passive and as inexpensive as possible.",

        # 8
        "Design a high-pass filter to band-limit a signal before sampling. "
        "The passband extends from {fc} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A simple DC-blocking filter is required. "
        "It must pass signals at {fc} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs} by at least {atten} dB. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a high-pass filter design for a general-purpose noise-reduction application. "
        "The -{pb} dB frequency should be no higher than {fc}. "
        "At {fs} the filter must deliver >= {atten} dB of attenuation. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage RC -------------------------------------------------------
    "rc_multi": [
        # 1
        "Design a high-pass filter with a steep roll-off for a signal conditioning application. "
        "The passband must extend from {fc} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs} must be attenuated by at least {atten} dB. "
        "Use only resistors and capacitors; minimise the total number of components.",

        # 2
        "Create a high-pass filter to strongly suppress low-frequency interference on a measurement line. "
        "Signals from {fc} upward should pass with less than {pb} dB loss. "
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
        "A signal must be heavily filtered to remove low-frequency content before entering a sensitive measurement circuit. "
        "The -{pb} dB point should be at or below {fc}. "
        "At least {atten} dB of suppression is needed at {fs}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a high-pass filter with sharp low-frequency rejection for an EMC application. "
        "Frequencies from {fc} upward must be passed with <= {pb} dB attenuation. "
        "Low-frequency interference at {fs} must be reduced by a minimum of {atten} dB. "
        "Use only resistors and capacitors, and favour the simplest topology that meets these figures.",

        # 7
        "A high-pass network is required to achieve high stopband attenuation without active components. "
        "The insertion loss must be below {pb} dB throughout the passband from {fc} upward. "
        "The circuit must achieve >= {atten} dB attenuation at {fs}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive high-pass filter for a data acquisition front end requiring strong low-frequency rejection. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Only R and C components; favour the lowest-cost design that meets the requirements.",

        # 9
        "Provide a high-pass filter design that achieves a high degree of low-frequency noise rejection using only passives. "
        "The passband extends from {fc} with a maximum of {pb} dB insertion loss. "
        "At {fs}, a minimum of {atten} dB attenuation is required. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A high-pass filter is needed with a demanding stopband specification. "
        "Frequencies from {fc} upward must be passed with <= {pb} dB loss. "
        "At {fs} the filter must attenuate signals by at least {atten} dB. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single-stage RC ---------------------------------------------
    "buffered_rc_single": [
        # 1
        "Design a high-pass filter to clean up the output of a high-impedance sensor. "
        "Signals at {fc} and above must pass with no more than {pb} dB of attenuation. "
        "Low-frequency interference at {fs} must be reduced by at least {atten} dB. "
        "The filter cutoff must be determined solely by the chosen R and C values. "
        "Keep the component count as small as possible.",

        # 2
        "Create a high-pass filter for a signal source whose output impedance is unknown and may vary with operating conditions. "
        "The passband should extend from {fc} with less than {pb} dB insertion loss. "
        "At {fs} the circuit should provide at least {atten} dB of rejection. "
        "The frequency response must remain stable regardless of what drives the input.",

        # 3
        "Specify a high-pass filter for a measurement line fed from a high-impedance resistive source. "
        "Frequencies from {fc} upward must be passed with <= {pb} dB loss. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "The design must ensure the source impedance has no effect on the filter's cutoff frequency; minimise component count.",

        # 4
        "A signal conditioning circuit is needed ahead of an ADC input driven by a resistive divider. "
        "The -{pb} dB point should be at or below {fc}. "
        "Low-frequency components at {fs} must be suppressed by at least {atten} dB. "
        "The RC network must see an ideal source so that its response matches the designed values exactly.",

        # 5
        "Design a high-pass filter for a signal path where the driving impedance is high enough to interact with the filter network. "
        "Pass signals from {fc} upward with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs}. "
        "The source must be decoupled from the filter so that loading effects do not shift the cutoff. Optimise for minimum BOM cost.",

        # 6
        "Build a high-frequency pass network to protect a downstream circuit from low-frequency interference. "
        "The source impedance is high and variable. "
        "The insertion loss in the passband from {fc} upward must stay below {pb} dB. "
        "At {fs}, the signal level must be reduced by at least {atten} dB. "
        "Ensure the filter behaviour is fully independent of the source; use as few components as possible.",

        # 7
        "A high-pass filter is required for a data acquisition front end. "
        "The signal originates from a sensor with a high Thevenin equivalent impedance. "
        "Signals above {fc} should experience at most {pb} dB of loss. "
        "Signals at {fs} and below should be attenuated by no less than {atten} dB. "
        "The filter must present a high impedance to the source while driving the RC network from a low-impedance node.",

        # 8
        "Design a high-pass filter to band-limit a signal before sampling. "
        "The source has a high output impedance that must not be allowed to detune the filter. "
        "The passband extends from {fc} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Ensure the cutoff is set by R and C alone; minimise part count.",

        # 9
        "A DC-blocking filter is required for a high-impedance signal source. "
        "It must pass signals at {fc} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs} by at least {atten} dB. "
        "The input impedance of the filter stage must be high enough that it does not load the source, "
        "and the RC network must be driven from a near-zero impedance node.",

        # 10
        "Provide a high-pass filter design for a noise-reduction application. "
        "The driving source has high and uncertain output impedance. "
        "The -{pb} dB frequency should be no higher than {fc}. "
        "At {fs} the filter must deliver >= {atten} dB of attenuation. "
        "The source impedance must be isolated from the RC network; keep the design as simple and cheap as possible.",
    ],

    # -- Buffered multi-stage RC ----------------------------------------------
    "buffered_rc_multi": [
        # 1
        "Design a high-pass filter with steep roll-off for a signal conditioning application driven by a high-impedance source. "
        "The passband must extend from {fc} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs} must be attenuated by at least {atten} dB. "
        "The source must be isolated from the RC ladder so the cutoff is determined by component values alone; minimise total component count.",

        # 2
        "Create a multi-stage high-pass filter to strongly suppress low-frequency interference on a measurement line. "
        "The line is driven from a high-impedance source that must not interact with the filter network. "
        "Signals from {fc} upward should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection at {fs}.",

        # 3
        "Specify a high-pass filter for a noise-sensitive signal path fed from a resistive source with high output impedance. "
        "The passband edge is {fc} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Decouple the source from the RC chain and use the fewest stages that meet the spec.",

        # 4
        "Design a high-pass filter to provide aggressive low-frequency noise rejection on a line with variable source impedance. "
        "Pass frequencies above {fc} with under {pb} dB loss. "
        "At {fs}, the attenuation must be at least {atten} dB. "
        "The filter response must be immune to changes in driving impedance. Optimise for minimum cost.",

        # 5
        "A signal with high and variable source impedance must be heavily filtered to remove low-frequency content before entering a sensitive measurement circuit. "
        "The -{pb} dB point should be at or below {fc}. "
        "At least {atten} dB of suppression is needed at {fs}. "
        "Ensure the RC network sees a low-impedance drive so that its response is fully predictable; keep component count low.",

        # 6
        "Design a high-pass filter with sharp low-frequency rejection for a precision measurement application. "
        "The input signal comes from a high-impedance resistive divider. "
        "Frequencies from {fc} upward must be passed with <= {pb} dB attenuation. "
        "Low-frequency interference at {fs} must be reduced by a minimum of {atten} dB. "
        "The RC ladder must be isolated from the source impedance; favour the simplest cascaded topology that meets the figures.",

        # 7
        "A multi-stage high-pass network is required to achieve high stopband attenuation. "
        "The source has a high Thevenin impedance that would otherwise interact with the filter and shift its cutoff. "
        "The insertion loss must be below {pb} dB throughout the passband from {fc} upward. "
        "The circuit must achieve >= {atten} dB attenuation at {fs}. Minimise total part count.",

        # 8
        "Design a high-pass filter for a data acquisition front end requiring strong low-frequency alias rejection and a precisely defined cutoff. "
        "The signal source has high output impedance; the filter response must not depend on it. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Drive the cascaded RC stages from a low-impedance node to guarantee the designed response.",

        # 9
        "Provide a multi-stage high-pass filter design that achieves a high degree of low-frequency noise rejection. "
        "The signal originates from a resistive source divider with significant output impedance. "
        "The passband extends from {fc} with a maximum of {pb} dB insertion loss. "
        "At {fs}, a minimum of {atten} dB attenuation is required. "
        "The source must be decoupled from the RC chain; use the fewest stages that satisfy all constraints.",

        # 10
        "A high-pass filter is needed with a demanding stopband specification. "
        "The driving source has high, uncertain output impedance that must not be allowed to detune the RC network. "
        "Frequencies from {fc} upward must be passed with <= {pb} dB loss. "
        "At {fs} the filter must attenuate signals by at least {atten} dB. "
        "Isolate the source from the multi-stage RC network and keep the design as inexpensive as possible.",
    ],
}