TEMPLATES: dict[str, list[str]] = {

    # -- Single-stage RC ------------------------------------------------------
    "rc_single": [
        # 1
        "Design a band-pass filter to isolate a sensor signal. "
        "Signals between {fc_low} and {fc_high} must pass with no more than {pb} dB of attenuation. "
        "Interference below {fs_low} and above {fs_high} must be reduced by at least {atten} dB. "
        "Use only resistors and capacitors, and keep the component count as small as possible.",

        # 2
        "Create a simple band-pass filter for a low-impedance signal source. "
        "The passband should span from {fc_low} to {fc_high} with less than {pb} dB insertion loss. "
        "At {fs_low} and {fs_high} the circuit should provide at least {atten} dB of rejection. "
        "Minimise cost; no active components are permitted.",

        # 3
        "Specify a band-pass RC network to isolate a narrow frequency band from a measurement line. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB loss. "
        "The attenuation at {fs_low} and {fs_high} must be >= {atten} dB. "
        "The design should use the fewest passive components that satisfy these requirements.",

        # 4
        "A signal conditioning circuit is needed to block both DC and high-frequency content before an ADC input. "
        "The passband should span {fc_low} to {fc_high} with a maximum of {pb} dB loss. "
        "Out-of-band components at {fs_low} and {fs_high} must be suppressed by at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Favour the simplest possible circuit.",

        # 5
        "Design a band-pass filter for a standard-impedance signal path. "
        "Pass signals from {fc_low} to {fc_high} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs_low} and {fs_high}. "
        "Use only passive components and optimise for minimum BOM cost.",

        # 6
        "Build a band-pass network to protect a downstream circuit from both low- and high-frequency interference. "
        "The insertion loss in the passband from {fc_low} to {fc_high} must stay below {pb} dB. "
        "At {fs_low} and {fs_high}, signal levels must be reduced by at least {atten} dB. "
        "Restrict the design to resistors and capacitors; use as few as possible.",

        # 7
        "A band-pass RC filter is required for a data acquisition front end. "
        "Signals between {fc_low} and {fc_high} should experience at most {pb} dB of loss. "
        "Signals at or below {fs_low} and at or above {fs_high} should be attenuated by no less than {atten} dB. "
        "The solution must be purely passive and as inexpensive as possible.",

        # 8
        "Design a band-pass filter to band-limit a signal before sampling. "
        "The passband spans {fc_low} to {fc_high} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs_low} and {fs_high}. "
        "Use only resistors and capacitors; minimise part count.",

        # 9
        "A band-pass filter is required to isolate a narrowband signal of interest. "
        "It must pass signals between {fc_low} and {fc_high} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs_low} and {fs_high} by at least {atten} dB. "
        "The circuit must use only passive components and should be as low-cost as possible.",

        # 10
        "Provide a band-pass filter design for a general-purpose noise-reduction application. "
        "The passband should span {fc_low} to {fc_high} with no more than {pb} dB loss. "
        "At {fs_low} and {fs_high} the filter must deliver >= {atten} dB of attenuation. "
        "No active components; keep the design as simple and cheap as possible.",
    ],

    # -- Multi-stage RC -------------------------------------------------------
    "rc_multi": [
        # 1
        "Design a band-pass filter with steep roll-off on both edges for a signal conditioning application. "
        "The passband must span {fc_low} to {fc_high} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs_low} and {fs_high} must be attenuated by at least {atten} dB. "
        "Use only resistors and capacitors; minimise the total number of components.",

        # 2
        "Create a band-pass filter to strongly suppress both low- and high-frequency interference on a measurement line. "
        "Signals from {fc_low} to {fc_high} should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection at {fs_low} and {fs_high}. "
        "No active components are allowed; keep the design as cost-effective as possible.",

        # 3
        "Specify a passive band-pass RC filter for a noise-sensitive signal path. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required at {fs_low} and {fs_high}. "
        "Use only resistors and capacitors; use the fewest stages that meet the spec.",

        # 4
        "Design a passive band-pass filter to provide aggressive out-of-band rejection on both sides. "
        "Pass frequencies between {fc_low} and {fc_high} with under {pb} dB loss. "
        "At {fs_low} and {fs_high}, the attenuation must be at least {atten} dB. "
        "Permitted components: resistors and capacitors only. Optimise for minimum cost.",

        # 5
        "A signal must be heavily filtered to remove both low- and high-frequency content before entering a sensitive measurement circuit. "
        "The passband spans {fc_low} to {fc_high} with a maximum of {pb} dB loss. "
        "At least {atten} dB of suppression is needed at {fs_low} and {fs_high}. "
        "Only passive R and C components may be used; keep the component count low.",

        # 6
        "Design a band-pass filter with sharp skirts on both edges for an EMC application. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB attenuation. "
        "Out-of-band interference at {fs_low} and {fs_high} must be reduced by a minimum of {atten} dB. "
        "Use only resistors and capacitors, and favour the simplest topology that meets these figures.",

        # 7
        "A band-pass network is required to achieve high stopband attenuation on both sides without active components. "
        "The insertion loss must be below {pb} dB throughout the passband from {fc_low} to {fc_high}. "
        "The circuit must achieve >= {atten} dB attenuation at {fs_low} and {fs_high}. "
        "Restrict components to resistors and capacitors; minimise total part count.",

        # 8
        "Design a passive band-pass filter for a data acquisition front end requiring strong out-of-band rejection. "
        "Signals between {fc_low} and {fc_high} must pass with less than {pb} dB loss. "
        "Signals at {fs_low} and {fs_high} must be suppressed by at least {atten} dB. "
        "Only R and C components; favour the lowest-cost design that meets the requirements.",

        # 9
        "Provide a band-pass filter design that achieves a high degree of out-of-band noise rejection using only passives. "
        "The passband spans {fc_low} to {fc_high} with a maximum of {pb} dB insertion loss. "
        "At {fs_low} and {fs_high}, a minimum of {atten} dB attenuation is required. "
        "No active components; use the fewest resistors and capacitors that satisfy all constraints.",

        # 10
        "A band-pass filter is needed with a demanding stopband specification on both sides. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB loss. "
        "At {fs_low} and {fs_high} the filter must attenuate signals by at least {atten} dB. "
        "Use only resistors and capacitors; keep the design as inexpensive as possible.",
    ],

    # -- Buffered single-stage RC ---------------------------------------------
    "buffered_rc_single": [
        # 1
        "Design a band-pass filter to isolate the signal of interest from a high-impedance sensor. "
        "Signals between {fc_low} and {fc_high} must pass with no more than {pb} dB of attenuation. "
        "Out-of-band interference at {fs_low} and {fs_high} must be reduced by at least {atten} dB. "
        "The filter cutoff frequencies must be determined solely by the chosen R and C values. "
        "Keep the component count as small as possible.",

        # 2
        "Create a band-pass filter for a signal source whose output impedance is unknown and may vary with operating conditions. "
        "The passband should span {fc_low} to {fc_high} with less than {pb} dB insertion loss. "
        "At {fs_low} and {fs_high} the circuit should provide at least {atten} dB of rejection. "
        "The frequency response must remain stable regardless of what drives the input.",

        # 3
        "Specify a band-pass filter for a measurement line fed from a high-impedance resistive source. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB loss. "
        "The attenuation at {fs_low} and {fs_high} must be >= {atten} dB. "
        "The design must ensure source impedance has no effect on the filter's cutoff frequencies; minimise component count.",

        # 4
        "A signal conditioning circuit is needed ahead of an ADC input driven by a resistive divider. "
        "The passband should span {fc_low} to {fc_high} with a maximum of {pb} dB loss. "
        "Components at {fs_low} and {fs_high} must be suppressed by at least {atten} dB. "
        "The RC network must see an ideal source so that its response matches the designed values exactly.",

        # 5
        "Design a band-pass filter for a signal path where the driving impedance is high enough to interact with the filter network. "
        "Pass signals from {fc_low} to {fc_high} with under {pb} dB loss. "
        "Provide at least {atten} dB of attenuation at {fs_low} and {fs_high}. "
        "The source must be decoupled from the filter so that loading effects do not shift the cutoffs. Optimise for minimum BOM cost.",

        # 6
        "Build a band-pass network to protect a downstream circuit from out-of-band interference. "
        "The source impedance is high and variable. "
        "The insertion loss in the passband from {fc_low} to {fc_high} must stay below {pb} dB. "
        "At {fs_low} and {fs_high}, signal levels must be reduced by at least {atten} dB. "
        "Ensure the filter behaviour is fully independent of the source; use as few components as possible.",

        # 7
        "A band-pass filter is required for a data acquisition front end. "
        "The signal originates from a sensor with a high Thevenin equivalent impedance. "
        "Signals between {fc_low} and {fc_high} should experience at most {pb} dB of loss. "
        "Signals at {fs_low} and {fs_high} should be attenuated by no less than {atten} dB. "
        "The filter must present a high impedance to the source while driving the RC network from a low-impedance node.",

        # 8
        "Design a band-pass filter to band-limit a signal before sampling. "
        "The source has a high output impedance that must not be allowed to detune the filter. "
        "The passband spans {fc_low} to {fc_high} and must have <= {pb} dB insertion loss. "
        "A minimum of {atten} dB rejection is required at {fs_low} and {fs_high}. "
        "Ensure the cutoffs are set by R and C alone; minimise part count.",

        # 9
        "A band-pass filter is required for a high-impedance signal source. "
        "It must pass signals between {fc_low} and {fc_high} with less than {pb} dB attenuation "
        "while rejecting frequencies at {fs_low} and {fs_high} by at least {atten} dB. "
        "The input impedance of the filter stage must be high enough that it does not load the source, "
        "and the RC network must be driven from a near-zero impedance node.",

        # 10
        "Provide a band-pass filter design for a noise-reduction application. "
        "The driving source has high and uncertain output impedance. "
        "The passband should span {fc_low} to {fc_high} with no more than {pb} dB loss. "
        "At {fs_low} and {fs_high} the filter must deliver >= {atten} dB of attenuation. "
        "The source impedance must be isolated from the RC network; keep the design as simple and cheap as possible.",
    ],

    # -- Buffered multi-stage RC ----------------------------------------------
    "buffered_rc_multi": [
        # 1
        "Design a band-pass filter with steep skirts on both edges for a signal conditioning application driven by a high-impedance source. "
        "The passband must span {fc_low} to {fc_high} with no more than {pb} dB of insertion loss. "
        "Frequencies at {fs_low} and {fs_high} must be attenuated by at least {atten} dB. "
        "The source must be isolated from the RC ladder so the cutoffs are determined by component values alone; minimise total component count.",

        # 2
        "Create a multi-stage band-pass filter to strongly suppress out-of-band interference on a measurement line. "
        "The line is driven from a high-impedance source that must not interact with the filter network. "
        "Signals from {fc_low} to {fc_high} should pass with less than {pb} dB loss. "
        "The circuit must provide at least {atten} dB of rejection at {fs_low} and {fs_high}.",

        # 3
        "Specify a band-pass filter for a noise-sensitive signal path fed from a resistive source with high output impedance. "
        "The passband spans {fc_low} to {fc_high} with <= {pb} dB loss. "
        "A minimum of {atten} dB attenuation is required at {fs_low} and {fs_high}. "
        "Decouple the source from the RC chain and use the fewest stages that meet the spec.",

        # 4
        "Design a band-pass filter to provide aggressive out-of-band rejection on a line with variable source impedance. "
        "Pass frequencies between {fc_low} and {fc_high} with under {pb} dB loss. "
        "At {fs_low} and {fs_high}, the attenuation must be at least {atten} dB. "
        "The filter response must be immune to changes in driving impedance. Optimise for minimum cost.",

        # 5
        "A signal with high and variable source impedance must be heavily filtered to isolate a narrowband signal of interest. "
        "The passband spans {fc_low} to {fc_high} with a maximum of {pb} dB loss. "
        "At least {atten} dB of suppression is needed at {fs_low} and {fs_high}. "
        "Ensure the RC network sees a low-impedance drive so that its response is fully predictable; keep component count low.",

        # 6
        "Design a band-pass filter with sharp skirts for a precision measurement application. "
        "The input signal comes from a high-impedance resistive divider. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB attenuation. "
        "Out-of-band interference at {fs_low} and {fs_high} must be reduced by a minimum of {atten} dB. "
        "The RC ladder must be isolated from the source impedance; favour the simplest cascaded topology that meets the figures.",

        # 7
        "A multi-stage band-pass network is required to achieve high stopband attenuation on both sides. "
        "The source has a high Thevenin impedance that would otherwise interact with the filter and shift its cutoffs. "
        "The insertion loss must be below {pb} dB throughout the passband from {fc_low} to {fc_high}. "
        "The circuit must achieve >= {atten} dB attenuation at {fs_low} and {fs_high}. Minimise total part count.",

        # 8
        "Design a band-pass filter for a data acquisition front end requiring strong out-of-band alias rejection and precisely defined cutoffs. "
        "The signal source has high output impedance; the filter response must not depend on it. "
        "Signals between {fc_low} and {fc_high} must pass with less than {pb} dB loss. "
        "Signals at {fs_low} and {fs_high} must be suppressed by at least {atten} dB. "
        "Drive the cascaded RC stages from a low-impedance node to guarantee the designed response.",

        # 9
        "Provide a multi-stage band-pass filter design that achieves a high degree of out-of-band noise rejection. "
        "The signal originates from a resistive source divider with significant output impedance. "
        "The passband spans {fc_low} to {fc_high} with a maximum of {pb} dB insertion loss. "
        "At {fs_low} and {fs_high}, a minimum of {atten} dB attenuation is required. "
        "The source must be decoupled from the RC chain; use the fewest stages that satisfy all constraints.",

        # 10
        "A band-pass filter is needed with a demanding stopband specification on both sides. "
        "The driving source has high, uncertain output impedance that must not be allowed to detune the RC network. "
        "Frequencies from {fc_low} to {fc_high} must be passed with <= {pb} dB loss. "
        "At {fs_low} and {fs_high} the filter must attenuate signals by at least {atten} dB. "
        "Isolate the source from the multi-stage RC network and keep the design as inexpensive as possible.",
    ],
}