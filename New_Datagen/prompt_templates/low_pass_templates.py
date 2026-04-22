TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage RC ------------------------------------------------------
    "rc_single": [
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
    "rc_multi": [
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
    
    # -- Buffered single-stage RC ---------------------------------------------
    "buffered_rc_single": [
        # 1
        "Design a low-pass filter to clean up the output of a high-impedance sensor. "
        "Signals at {fc} and below must pass with no more than {pb} dB of attenuation. "
        "Interference at {fs} must be reduced by at least {atten} dB. "
        "The filter cutoff must be determined solely by the chosen R and C values. "
        "Keep the component count as small as possible.",

        # 2
        "Create a low-pass filter for a signal source whose output impedance is unknown and may vary with operating conditions. "
        "The passband should extend to {fc} with less than {pb} dB insertion loss. "
        "At {fs} the circuit should provide at least {atten} dB of rejection. "
        "The frequency response must remain stable regardless of what drives the input.",

        # 3
        "Specify a low-pass filter for a measurement line fed from a high-impedance resistive source. "
        "Frequencies up to {fc} must be passed with <= {pb} dB loss. "
        "The attenuation at {fs} must be >= {atten} dB. "
        "The design must ensure the source impedance has no effect on the filter's cutoff frequency; minimise component count.",

        # 4
        "A signal conditioning circuit is needed ahead of an ADC input driven by a resistive divider. "
        "The -{pb} dB point should be at or above {fc}. "
        "Noise components at {fs} must be suppressed by at least {atten} dB. "
        "The RC network must see an ideal source so that its response matches the designed values exactly.",

        # 5
        "Design a low-pass filter for a signal path where the driving impedance is high enough to interact with the filter network. "
        "Pass signals through {fc} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs}. "
        "The source must be decoupled from the filter so that loading effects do not shift the cutoff. Optimise for minimum BOM cost.",

        # 6
        "Build a low-frequency pass network to protect a downstream circuit from high-frequency interference. "
        "The source impedance is high and variable. "
        "The insertion loss in the passband up to {fc} must stay below {pb} dB. "
        "At {fs}, the signal level must be reduced by at least {atten} dB. "
        "Ensure the filter behaviour is fully independent of the source; use as few components as possible.",

        # 7
        "A low-pass filter is required for a data acquisition front end. "
        "The signal originates from a sensor with a high Thevenin equivalent impedance. "
        "Signals below {fc} should experience at most {pb} dB of loss. "
        "Signals at {fs} and above should be attenuated by no less than {atten} dB. "
        "The filter must present a high impedance to the source while driving the RC network from a low-impedance node.",

        # 8
        "Design a low-pass filter to band-limit a signal before sampling. "
        "The source has a high output impedance that must not be allowed to detune the filter. "
        "The passband extends to {fc} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs}. "
        "Ensure the cutoff is set by R and C alone; minimise part count.",

        # 9
        "An anti-aliasing filter is required for a high-impedance signal source. "
        "It must pass signals at {fc} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs} by at least {atten} dB. "
        "The input impedance of the filter stage must be high enough that it does not load the source, "
        "and the RC network must be driven from a near-zero impedance node.",

        # 10
        "Provide a low-pass filter design for a noise-reduction application. "
        "The driving source has high and uncertain output impedance. "
        "The -{pb} dB frequency should be no lower than {fc}. "
        "At {fs} the filter must deliver >= {atten} dB of attenuation. "
        "The source impedance must be isolated from the RC network; keep the design as simple and cheap as possible.",
    ],

    # -- Buffered multi-stage RC ----------------------------------------------
    "buffered_rc_multi": [
        # 1
        "Design a low-pass filter with steep roll-off for a signal conditioning application driven by a high-impedance source. "
        "The passband must extend to {fc} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs} must be attenuated by at least {atten} dB. "
        "The source must be isolated from the RC ladder so the cutoff is determined by component values alone; minimise total component count.",

        # 2
        "Create a multi-stage low-pass filter to strongly suppress high-frequency interference on a measurement line. "
        "The line is driven from a high-impedance source that must not interact with the filter network. "
        "Signals up to {fc} should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection at {fs}.",

        # 3
        "Specify a low-pass filter for a noise-sensitive signal path fed from a resistive source with high output impedance. "
        "The passband edge is {fc} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required at {fs}. "
        "Decouple the source from the RC chain and use the fewest stages that meet the spec.",

        # 4
        "Design a low-pass filter to provide aggressive noise rejection on a line with variable source impedance. "
        "Pass frequencies below {fc} with under {pb} dB loss. "
        "At {fs}, the attenuation must be at least {atten} dB. "
        "The filter response must be immune to changes in driving impedance. Optimise for minimum cost.",

        # 5
        "A signal with high and variable source impedance must be heavily filtered before entering a sensitive measurement circuit. "
        "The -{pb} dB point should be at or above {fc}. "
        "At least {atten} dB of suppression is needed at {fs}. "
        "Ensure the RC network sees a low-impedance drive so that its response is fully predictable; keep component count low.",

        # 6
        "Design a low-pass filter with sharp high-frequency rejection for a precision measurement application. "
        "The input signal comes from a high-impedance resistive divider. "
        "Frequencies up to {fc} must be passed with <= {pb} dB attenuation. "
        "Interference at {fs} must be reduced by a minimum of {atten} dB. "
        "The RC ladder must be isolated from the source impedance; favour the simplest cascaded topology that meets the figures.",

        # 7
        "A multi-stage low-pass network is required to achieve high stopband attenuation. "
        "The source has a high Thevenin impedance that would otherwise interact with the filter and shift its cutoff. "
        "The insertion loss must be below {pb} dB throughout the passband up to {fc}. "
        "The circuit must achieve >= {atten} dB attenuation at {fs}. Minimise total part count.",

        # 8
        "Design a low-pass filter for a data acquisition front end requiring strong alias rejection and a precisely defined cutoff. "
        "The signal source has high output impedance; the filter response must not depend on it. "
        "Signals at {fc} must pass with less than {pb} dB loss. "
        "Signals at {fs} must be suppressed by at least {atten} dB. "
        "Drive the cascaded RC stages from a low-impedance node to guarantee the designed response.",

        # 9
        "Provide a multi-stage low-pass filter design that achieves a high degree of noise rejection. "
        "The signal originates from a resistive source divider with significant output impedance. "
        "The passband extends to {fc} with a maximum of {pb} dB insertion loss. "
        "At {fs}, a minimum of {atten} dB attenuation is required. "
        "The source must be decoupled from the RC chain; use the fewest stages that satisfy all constraints.",

        # 10
        "A low-pass filter is needed with a demanding stopband specification. "
        "The driving source has high, uncertain output impedance that must not be allowed to detune the RC network. "
        "Frequencies up to {fc} must be passed with <= {pb} dB loss. "
        "At {fs} the filter must attenuate signals by at least {atten} dB. "
        "Isolate the source from the multi-stage RC network and keep the design as inexpensive as possible.",
    ],
}