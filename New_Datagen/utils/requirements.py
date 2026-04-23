"""
Appends a structured REQUIREMENTS block to a prompt string.
Keeps the exact numeric values from the dataset so the model (and later the
agentic feedback loop) can reference them directly.
"""


def _hz(f: float) -> str:
    if f >= 1e6:
        return f"{f/1e6:.4g} MHz"
    if f >= 1e3:
        return f"{f/1e3:.4g} kHz"
    return f"{f:.4g} Hz"


def lpf_requirements(prompt: str, f_pass: float, f_stop: float,
                     pb_db: float, atten_db: float) -> str:
    block = (
        "\n\nREQUIREMENTS:\n"
        f"  Type: low-pass filter\n"
        f"  Passband edge (fc): {_hz(f_pass)}  [max loss: {pb_db} dB]\n"
        f"  Stopband edge (fs): {_hz(f_stop)}  [min attenuation: {atten_db} dB]"
    )
    return prompt + block


def hpf_requirements(prompt: str, f_pass: float, f_stop: float,
                     pb_db: float, atten_db: float) -> str:
    block = (
        "\n\nREQUIREMENTS:\n"
        f"  Type: high-pass filter\n"
        f"  Passband edge (fc): {_hz(f_pass)}  [max loss: {pb_db} dB]\n"
        f"  Stopband edge (fs): {_hz(f_stop)}  [min attenuation: {atten_db} dB]"
    )
    return prompt + block


def bpf_requirements(prompt: str, fc_low: float, fc_high: float,
                     fs_low: float, fs_high: float,
                     pb_db: float, atten_db: float) -> str:
    block = (
        "\n\nREQUIREMENTS:\n"
        f"  Type: band-pass filter\n"
        f"  Lower passband edge (fc_low): {_hz(fc_low)}  [max loss: {pb_db} dB]\n"
        f"  Upper passband edge (fc_high): {_hz(fc_high)}  [max loss: {pb_db} dB]\n"
        f"  Lower stopband edge (fs_low): {_hz(fs_low)}  [min attenuation: {atten_db} dB]\n"
        f"  Upper stopband edge (fs_high): {_hz(fs_high)}  [min attenuation: {atten_db} dB]"
    )
    return prompt + block


def notch_requirements(prompt: str, f_notch: float, fc_low: float, fc_high: float,
                       f_stop: float, pb_db: float, atten_db: float) -> str:
    block = (
        "\n\nREQUIREMENTS:\n"
        f"  Type: notch filter\n"
        f"  Notch centre: {_hz(f_notch)}\n"
        f"  Notch bandwidth (-3 dB): {_hz(fc_low)} – {_hz(fc_high)}\n"
        f"  Stopband sample (fs): {_hz(f_stop)}  [min attenuation: {atten_db} dB]\n"
        f"  Passband loss: ≤ {pb_db} dB"
    )
    return prompt + block
