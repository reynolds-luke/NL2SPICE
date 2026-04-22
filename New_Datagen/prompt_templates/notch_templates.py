TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage RC ------------------------------------------------------
    "rc_single": [
        # 1
        "Design a notch filter to reject interference at a specific frequency. "
        "Signals below {fs_low} and above {fs_high} must pass with no more than {pb} dB of attenuation. "
        "The interference at {fc_low} to {fc_high} must be reduced by at least {atten} dB. "
        "Use only resistors and capacitors, and keep the component count as small as possible.",

        # 2
        "Create a simple notch filter for a low-impedance signal source. "
        "The passbands below {fs_low} and above {fs_high} should have less than {pb} dB insertion loss. "
        "In the stopband from {fc_low} to {fc_high} the circuit should provide at least {atten} dB of rejection. "
        "Minimise cost; no active components are permitted.",

        # 3
        "Specify a notch RC network to suppress a narrow interference band on a measurement line. "
        "Frequencies below {fs_low} and above {fs_high} must be passed with <= {pb} dB loss. "
        "The attenuation between {fc_low} and {fc_high} must be >= {atten} dB. "
        "The design should use the fewest passive components that satisfy these requirements.",

        # 4
        "A signal conditioning circuit is needed to reject a narrowband interference tone before an ADC input. "
        "The passbands below {fs_low} and above {fs_high} should have a maximum of {pb} dB loss. "
        "The interference band from {fc_low} to {fc_high} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Favour the simplest possible circuit.",

        # 5
        "Design a notch filter for a standard-impedance signal path. "
        "Pass signals below {fs_low} and above {fs_high} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation between {fc_low} and {fc_high}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a notch network to protect a downstream circuit from a narrowband interference source. "
        "The insertion loss in the passbands below {fs_low} and above {fs_high} must stay below {pb} dB. "
        "Between {fc_low} and {fc_high}, signal levels must be reduced by at least {atten} dB. "
        "Restrict the design to resistors and capacitors; use as few as possible.",

        # 7
        "A notch RC filter is required for a data acquisition front end. "
        "Signals below {fs_low} and above {fs_high} should experience at most {pb} dB of loss. "
        "Signals between {fc_low} and {fc_high} should be attenuated by no less than {atten} dB. "
        "The solution must be purely passive and as inexpensive as possible.",

        # 8
        "Design a notch filter to eliminate a specific interference tone before sampling. "
        "The passbands below {fs_low} and above {fs_high} must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required between {fc_low} and {fc_high}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A notch filter is required to suppress a narrowband interference tone. "
        "It must pass signals below {fs_low} and above {fs_high} with less than {pb} dB attenuation "
        "while rejecting frequencies between {fc_low} and {fc_high} by at least {atten} dB. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a notch filter design for a general-purpose interference-rejection application. "
        "The passbands below {fs_low} and above {fs_high} should have no more than {pb} dB loss. "
        "Between {fc_low} and {fc_high} the filter must deliver >= {atten} dB of attenuation. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage RC -------------------------------------------------------
    "rc_multi": [
        # 1
        "Design a notch filter with deep, steep rejection for a signal conditioning application. "
        "The passbands must span below {fs_low} and above {fs_high} with no more than {pb} dB of insertion loss. "
        "Frequencies between {fc_low} and {fc_high} must be attenuated by at least {atten} dB. "
        "Use only resistors and capacitors; minimise the total number of components.",

        # 2
        "Create a notch filter to strongly suppress a narrowband tone on a measurement line. "
        "Signals below {fs_low} and above {fs_high} should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection between {fc_low} and {fc_high}. "
        "No active components are allowed; keep the design as cost-effective as possible.",

        # 3
        "Specify a passive notch RC filter for a noise-sensitive signal path. "
        "The passbands span below {fs_low} and above {fs_high} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required between {fc_low} and {fc_high}. "
        "Use only resistors and capacitors; use the fewest stages that meet the spec.",

        # 4
        "Design a passive notch filter to provide deep stopband rejection of a narrowband interference source. "
        "Pass frequencies below {fs_low} and above {fs_high} with under {pb} dB loss. "
        "Between {fc_low} and {fc_high}, the attenuation must be at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Optimise for minimum cost.",

        # 5
        "A signal must be heavily filtered to remove a narrowband tone before entering a sensitive measurement circuit. "
        "The passbands span below {fs_low} and above {fs_high} with a maximum of {pb} dB loss. "
        "At least {atten} dB of suppression is needed between {fc_low} and {fc_high}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a notch filter with deep rejection for an EMC application. "
        "Frequencies below {fs_low} and above {fs_high} must be passed with <= {pb} dB attenuation. "
        "In-band interference between {fc_low} and {fc_high} must be reduced by a minimum of {atten} dB. "
        "Use only resistors and capacitors, and favour the simplest topology that meets these figures.",

        # 7
        "A notch network is required to achieve high stopband attenuation without active components. "
        "The insertion loss must be below {pb} dB throughout the passbands below {fs_low} and above {fs_high}. "
        "The circuit must achieve >= {atten} dB attenuation between {fc_low} and {fc_high}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive notch filter for a data acquisition front end requiring deep rejection of a specific tone. "
        "Signals below {fs_low} and above {fs_high} must pass with less than {pb} dB loss. "
        "Signals between {fc_low} and {fc_high} must be suppressed by at least {atten} dB. "
        "Only R and C components; favour the lowest-cost design that meets the requirements.",

        # 9
        "Provide a notch filter design that achieves deep rejection of a narrowband interference tone using only passives. "
        "The passbands span below {fs_low} and above {fs_high} with a maximum of {pb} dB insertion loss. "
        "Between {fc_low} and {fc_high}, a minimum of {atten} dB attenuation is required. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A notch filter is needed with a demanding stopband specification around a single interference frequency. "
        "Frequencies below {fs_low} and above {fs_high} must be passed with <= {pb} dB loss. "
        "Between {fc_low} and {fc_high} the filter must attenuate signals by at least {atten} dB. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single-stage RC ---------------------------------------------
    "buffered_rc_single": [
        # 1
        "Design a notch filter to reject a narrowband interference tone from a high-impedance sensor signal. "
        "Signals below {fs_low} and above {fs_high} must pass with no more than {pb} dB of attenuation. "
        "Out-of-band interference between {fc_low} and {fc_high} must be reduced by at least {atten} dB. "
        "The filter notch frequency must be determined solely by the chosen R and C values. "
        "Keep the component count as small as possible.",

        # 2
        "Create a notch filter for a signal source whose output impedance is unknown and may vary with operating conditions. "
        "The passbands below {fs_low} and above {fs_high} should have less than {pb} dB insertion loss. "
        "Between {fc_low} and {fc_high} the circuit should provide at least {atten} dB of rejection. "
        "The notch frequency must remain stable regardless of what drives the input.",

        # 3
        "Specify a notch filter for a measurement line fed from a high-impedance resistive source. "
        "Frequencies below {fs_low} and above {fs_high} must be passed with <= {pb} dB loss. "
        "The attenuation between {fc_low} and {fc_high} must be >= {atten} dB. "
        "The design must ensure source impedance has no effect on the notch frequency; minimise component count.",

        # 4
        "A signal conditioning circuit is needed ahead of an ADC input driven by a resistive divider. "
        "The passbands below {fs_low} and above {fs_high} should have a maximum of {pb} dB loss. "
        "The tone between {fc_low} and {fc_high} must be suppressed by at least {atten} dB. "
        "The RC network must see an ideal source so that its notch frequency matches the designed value exactly.",

        # 5
        "Design a notch filter for a signal path where the driving impedance is high enough to interact with the filter network. "
        "Pass signals below {fs_low} and above {fs_high} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation between {fc_low} and {fc_high}. "
        "The source must be decoupled from the filter so that loading effects do not shift the notch frequency. Optimise for minimum BOM cost.",

        # 6
        "Build a notch network to suppress narrowband interference before a downstream circuit. "
        "The source impedance is high and variable. "
        "The insertion loss in the passbands below {fs_low} and above {fs_high} must stay below {pb} dB. "
        "Between {fc_low} and {fc_high}, signal levels must be reduced by at least {atten} dB. "
        "Ensure the filter behaviour is fully independent of the source; use as few components as possible.",

        # 7
        "A notch filter is required for a data acquisition front end. "
        "The signal originates from a sensor with a high Thevenin equivalent impedance. "
        "Signals below {fs_low} and above {fs_high} should experience at most {pb} dB of loss. "
        "Signals between {fc_low} and {fc_high} should be attenuated by no less than {atten} dB. "
        "The filter must present a high impedance to the source while driving the RC network from a low-impedance node.",

        # 8
        "Design a notch filter to eliminate a specific interference tone before sampling. "
        "The source has a high output impedance that must not be allowed to shift the notch frequency. "
        "The passbands below {fs_low} and above {fs_high} must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required between {fc_low} and {fc_high}. "
        "Ensure the notch is set by R and C alone; minimise part count.",

        # 9
        "A notch filter is required for a high-impedance signal source. "
        "It must pass signals below {fs_low} and above {fs_high} with less than {pb} dB attenuation "
        "while rejecting frequencies between {fc_low} and {fc_high} by at least {atten} dB. "
        "The input impedance of the filter stage must be high enough that it does not load the source, "
        "and the RC network must be driven from a near-zero impedance node.",

        # 10
        "Provide a notch filter design for an interference-rejection application. "
        "The driving source has high and uncertain output impedance. "
        "The passbands below {fs_low} and above {fs_high} should have no more than {pb} dB loss. "
        "Between {fc_low} and {fc_high} the filter must deliver >= {atten} dB of attenuation. "
        "The source impedance must be isolated from the RC network; keep the design as simple and cheap as possible.",
    ],

    # -- Buffered multi-stage RC ----------------------------------------------
    "buffered_rc_multi": [
        # 1
        "Design a notch filter with deep rejection and steep skirts for a signal conditioning application driven by a high-impedance source. "
        "The passbands must span below {fs_low} and above {fs_high} with no more than {pb} dB of insertion loss. "
        "Frequencies between {fc_low} and {fc_high} must be attenuated by at least {atten} dB. "
        "The source must be isolated from the RC ladder so the notch frequency is determined by component values alone; minimise total component count.",

        # 2
        "Create a multi-stage notch filter to strongly suppress a narrowband tone on a measurement line. "
        "The line is driven from a high-impedance source that must not interact with the filter network. "
        "Signals below {fs_low} and above {fs_high} should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection between {fc_low} and {fc_high}.",

        # 3
        "Specify a notch filter for a noise-sensitive signal path fed from a resistive source with high output impedance. "
        "The passbands span below {fs_low} and above {fs_high} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required between {fc_low} and {fc_high}. "
        "Decouple the source from the RC chain and use the fewest stages that meet the spec.",

        # 4
        "Design a notch filter to provide deep rejection of a narrowband tone on a line with variable source impedance. "
        "Pass frequencies below {fs_low} and above {fs_high} with under {pb} dB loss. "
        "Between {fc_low} and {fc_high}, the attenuation must be at least {atten} dB. "
        "The filter response must be immune to changes in driving impedance. Optimise for minimum cost.",

        # 5
        "A signal with high and variable source impedance must be filtered to remove a specific narrowband interference tone. "
        "The passbands span below {fs_low} and above {fs_high} with a maximum of {pb} dB loss. "
        "At least {atten} dB of suppression is needed between {fc_low} and {fc_high}. "
        "Ensure the RC network sees a low-impedance drive so that its notch frequency is fully predictable; keep component count low.",

        # 6
        "Design a notch filter with deep rejection for a precision measurement application. "
        "The input signal comes from a high-impedance resistive divider. "
        "Frequencies below {fs_low} and above {fs_high} must be passed with <= {pb} dB attenuation. "
        "The interference between {fc_low} and {fc_high} must be reduced by a minimum of {atten} dB. "
        "The RC ladder must be isolated from the source impedance; favour the simplest cascaded topology that meets the figures.",

        # 7
        "A multi-stage notch network is required to achieve deep stopband rejection of a narrowband tone. "
        "The source has a high Thevenin impedance that would otherwise interact with the filter and shift its notch frequency. "
        "The insertion loss must be below {pb} dB throughout the passbands below {fs_low} and above {fs_high}. "
        "The circuit must achieve >= {atten} dB attenuation between {fc_low} and {fc_high}. Minimise total part count.",

        # 8
        "Design a notch filter for a data acquisition front end requiring deep rejection of a specific interference tone and a precisely defined notch frequency. "
        "The signal source has high output impedance; the filter response must not depend on it. "
        "Signals below {fs_low} and above {fs_high} must pass with less than {pb} dB loss. "
        "Signals between {fc_low} and {fc_high} must be suppressed by at least {atten} dB. "
        "Drive the cascaded RC stages from a low-impedance node to guarantee the designed response.",

        # 9
        "Provide a multi-stage notch filter design that achieves deep rejection of a narrowband interference tone. "
        "The signal originates from a resistive source divider with significant output impedance. "
        "The passbands span below {fs_low} and above {fs_high} with a maximum of {pb} dB insertion loss. "
        "Between {fc_low} and {fc_high}, a minimum of {atten} dB attenuation is required. "
        "The source must be decoupled from the RC chain; use the fewest stages that satisfy all constraints.",

        # 10
        "A notch filter is needed with a demanding stopband specification around a specific interference frequency. "
        "The driving source has high, uncertain output impedance that must not be allowed to shift the notch frequency. "
        "Frequencies below {fs_low} and above {fs_high} must be passed with <= {pb} dB loss. "
        "Between {fc_low} and {fc_high} the filter must attenuate signals by at least {atten} dB. "
        "Isolate the source from the multi-stage RC network and keep the design as inexpensive as possible.",
    ],
}