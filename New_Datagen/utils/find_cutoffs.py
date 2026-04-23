import math
import matplotlib.pyplot as plt
from .measure_atten import simulate_attenuation


def find_lowpass_cutoff_frequency(
    netlist_body: str,
    tolerance: float = 0.5,
    create_graph: bool = False,
) -> tuple[float | None, plt.Figure | None]:
    """
    Find the -3dB cutoff frequency of a low-pass filter by binary searching
    over sampled attenuation values, and return a Bode magnitude plot of all
    sampled points.

    Assumes:
      - The filter passes DC (gain ≈ 0 dB at 1 Hz)
      - Gain rolls off monotonically with frequency (e.g. RC ladder, Butterworth)

    Not suitable for high-pass, band-pass, band-stop, or filters with
    passband ripple (Chebyshev, elliptic).

    Parameters
    ----------
    netlist_body : str
        SPICE netlist fragment passed directly to simulate_attenuation.
    tolerance : float
        Stop bisecting when the bracket width is within this fraction of the
        midpoint frequency. Default 0.01 (1%). Increase for fewer samples and
        a rougher estimate; decrease for more precision.

    Returns
    -------
    tuple[float | None, plt.Figure | None]
        - The -3dB cutoff frequency in Hz, or None on any simulation failure.
        - A matplotlib Figure showing the Bode plot, or None on failure.
    """
    samples: list[tuple[float, float]] = []

    def sample(freq: float) -> float | None:
        val = simulate_attenuation(netlist_body, frequency=freq)
        if val is not None:
            samples.append((freq, val))
        return val

    # Baseline near-DC gain
    baseline_db = sample(1.0)
    if baseline_db is None:
        return None, None
    target_db = baseline_db - 3.0

    # Walk up in decades to find an upper bound where gain is below target
    upper_freq = 10.0
    for _ in range(12):
        val = sample(upper_freq)
        if val is None:
            return None, None
        if val < target_db:
            break
        upper_freq *= 10.0
    else:
        return None, None

    lower_freq = upper_freq / 10.0

    # Binary search in log-frequency space, exit once bracket is within tolerance
    while (upper_freq - lower_freq) / (upper_freq + lower_freq) * 2 > tolerance:
        mid_freq = math.exp((math.log(lower_freq) + math.log(upper_freq)) / 2)
        val = sample(mid_freq)
        if val is None:
            return None, None
        if val < target_db:
            upper_freq = mid_freq
        else:
            lower_freq = mid_freq

    cutoff_freq = math.exp((math.log(lower_freq) + math.log(upper_freq)) / 2)

    if create_graph:
        samples.sort(key=lambda x: x[0])
        freqs, dbs = zip(*samples)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.scatter(freqs, dbs, s=18, zorder=5, label="Samples")
        ax.plot(freqs, dbs, linewidth=1, alpha=0.6, label="Response")
        ax.axvline(
            cutoff_freq,
            color="red",
            linewidth=1,
            linestyle="--",
            label=f"f_c = {cutoff_freq:,.1f} Hz",
        )
        ax.axhline(
            target_db,
            color="gray",
            linewidth=0.8,
            linestyle=":",
            label=f"{target_db:.1f} dB",
        )
        ax.set_xscale("log")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Attenuation (dB)")
        ax.set_title("Low-pass filter — Bode magnitude plot")
        ax.legend()
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        return cutoff_freq, fig
    else:
        return cutoff_freq, None


def find_highpass_cutoff_frequency(
    netlist_body: str,
    tolerance: float = 0.5,
    create_graph: bool = False,
) -> tuple[float | None, plt.Figure | None]:
    """
    Find the -3dB cutoff frequency of a high-pass filter by binary searching
    over sampled attenuation values, and return a Bode magnitude plot of all
    sampled points.

    Assumes:
      - The filter passes high frequencies (gain ≈ 0 dB at a sufficiently high
        frequency, used as the passband reference)
      - Gain rolls off monotonically as frequency decreases (e.g. RC high-pass,
        first-order Butterworth)

    Not suitable for low-pass, band-pass, band-stop, or filters with
    passband ripple (Chebyshev, elliptic).

    Parameters
    ----------
    netlist_body : str
        SPICE netlist fragment passed directly to simulate_attenuation.
    tolerance : float
        Stop bisecting when the bracket width is within this fraction of the
        midpoint frequency. Default 0.5. Increase for fewer samples and
        a rougher estimate; decrease for more precision.

    Returns
    -------
    tuple[float | None, plt.Figure | None]
        - The -3dB cutoff frequency in Hz, or None on any simulation failure.
        - A matplotlib Figure showing the Bode plot, or None on failure.
    """
    samples: list[tuple[float, float]] = []

    def sample(freq: float) -> float | None:
        val = simulate_attenuation(netlist_body, frequency=freq)
        if val is not None:
            samples.append((freq, val))
        return val

    # Walk up in decades to find a passband reference (gain plateaus at high freq)
    # Start at 1 MHz and walk up until gain stops rising significantly.
    ref_freq = 1e6
    for _ in range(6):
        val = sample(ref_freq)
        if val is None:
            return None, None
        next_val = sample(ref_freq * 10.0)
        if next_val is None:
            return None, None
        # If doubling the decade changes gain by less than 0.5 dB, we're in the passband
        if abs(next_val - val) < 0.5:
            break
        ref_freq *= 10.0
    else:
        return None, None

    baseline_db = next_val  # passband reference at the higher of the two probed freqs
    upper_freq = ref_freq * 10.0
    target_db = baseline_db - 3.0

    # Walk down in decades to find a lower bound where gain is below the target
    lower_freq = upper_freq / 10.0
    for _ in range(12):
        val = sample(lower_freq)
        if val is None:
            return None, None
        if val < target_db:
            break
        lower_freq /= 10.0
    else:
        return None, None

    upper_freq = lower_freq * 10.0

    # Binary search in log-frequency space, exit once bracket is within tolerance
    while (upper_freq - lower_freq) / (upper_freq + lower_freq) * 2 > tolerance:
        mid_freq = math.exp((math.log(lower_freq) + math.log(upper_freq)) / 2)
        val = sample(mid_freq)
        if val is None:
            return None, None
        if val < target_db:
            lower_freq = mid_freq   # ← inverted vs low-pass: too low → raise floor
        else:
            upper_freq = mid_freq

    cutoff_freq = math.exp((math.log(lower_freq) + math.log(upper_freq)) / 2)

    if create_graph:
        samples.sort(key=lambda x: x[0])
        freqs, dbs = zip(*samples)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.scatter(freqs, dbs, s=18, zorder=5, label="Samples")
        ax.plot(freqs, dbs, linewidth=1, alpha=0.6, label="Response")
        ax.axvline(
            cutoff_freq,
            color="red",
            linewidth=1,
            linestyle="--",
            label=f"f_c = {cutoff_freq:,.1f} Hz",
        )
        ax.axhline(
            target_db,
            color="gray",
            linewidth=0.8,
            linestyle=":",
            label=f"{target_db:.1f} dB",
        )
        ax.set_xscale("log")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Attenuation (dB)")
        ax.set_title("High-pass filter — Bode magnitude plot")
        ax.legend()
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        return cutoff_freq, fig
    else:
        return cutoff_freq, None


def find_bandpass_cutoff_frequencies(
    netlist_body: str,
    tolerance: float = 0.5,
    create_graph: bool = False,
) -> tuple[tuple[float, float] | None, plt.Figure | None]:
    """
    Find the lower and upper -3dB cutoff frequencies of a band-pass filter by
    binary searching over sampled attenuation values, and return a Bode
    magnitude plot of all sampled points.

    Assumes:
      - The filter has a single passband peak with gain rolling off
        monotonically on both sides (e.g. RLC band-pass, second-order
        Butterworth band-pass).
      - The passband reference is the peak gain found by probing decades
        around the center frequency.

    Not suitable for high-pass, low-pass, band-stop, or filters with
    passband ripple (Chebyshev, elliptic).

    Parameters
    ----------
    netlist_body : str
        SPICE netlist fragment passed directly to simulate_attenuation.
    tolerance : float
        Stop bisecting when the bracket width is within this fraction of the
        midpoint frequency. Default 0.5. Increase for fewer samples and
        a rougher estimate; decrease for more precision.

    Returns
    -------
    tuple[tuple[float, float] | None, plt.Figure | None]
        - A (f_low, f_high) pair of -3dB cutoff frequencies in Hz,
          or None on any simulation failure.
        - A matplotlib Figure showing the Bode plot, or None on failure.
    """
    samples: list[tuple[float, float]] = []

    def sample(freq: float) -> float | None:
        val = simulate_attenuation(netlist_body, frequency=freq)
        if val is not None:
            samples.append((freq, val))
        return val

    # --- Step 1: Find the peak (passband reference) by sweeping decades ---
    # Probe from 1 Hz to 1 GHz in decade steps, track the best gain seen.
    probe_freqs = [10.0 ** e for e in range(0, 10)]  # 1 Hz → 1 GHz
    peak_db = -math.inf
    peak_freq = None

    for freq in probe_freqs:
        val = sample(freq)
        if val is None:
            return None, None
        if val > peak_db:
            peak_db = val
            peak_freq = freq

    if peak_freq is None:
        return None, None

    target_db = peak_db - 3.0

    # --- Step 2: Refine the peak with a ternary search in log-frequency space ---
    # Narrow down to the decade bracket containing the peak, then bisect.
    lo = peak_freq / 10.0
    hi = peak_freq * 10.0
    for _ in range(12):
        width = (hi - lo) / (hi + lo) * 2
        if width < tolerance * 0.1:
            break
        m1 = math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) / 3)
        m2 = math.exp(math.log(lo) + 2 * (math.log(hi) - math.log(lo)) / 3)
        v1 = sample(m1)
        v2 = sample(m2)
        if v1 is None or v2 is None:
            return None, None
        if v1 < v2:
            lo = m1
        else:
            hi = m2
        # Update peak if we found something better
        for f, v in [(m1, v1), (m2, v2)]:
            if v > peak_db:
                peak_db = v
                peak_freq = f
                target_db = peak_db - 3.0

    # --- Step 3: Binary search for the lower -3dB cutoff ---
    # Find a lower bound clearly below the target.
    lower_search_lo = 1.0
    lower_search_hi = peak_freq

    val_at_lo = sample(lower_search_lo)
    if val_at_lo is None:
        return None, None

    if val_at_lo >= target_db:
        # Passband extends all the way to 1 Hz — not a band-pass filter
        return None, None

    while (lower_search_hi - lower_search_lo) / (lower_search_hi + lower_search_lo) * 2 > tolerance:
        mid = math.exp((math.log(lower_search_lo) + math.log(lower_search_hi)) / 2)
        val = sample(mid)
        if val is None:
            return None, None
        if val < target_db:
            lower_search_lo = mid  # below target → raise floor
        else:
            lower_search_hi = mid  # above target → lower ceiling

    f_low = math.exp((math.log(lower_search_lo) + math.log(lower_search_hi)) / 2)

    # --- Step 4: Binary search for the upper -3dB cutoff ---
    upper_search_lo = peak_freq
    upper_search_hi = 1e10  # 10 GHz ceiling

    val_at_hi = sample(upper_search_hi)
    if val_at_hi is None:
        return None, None

    if val_at_hi >= target_db:
        return None, None

    while (upper_search_hi - upper_search_lo) / (upper_search_hi + upper_search_lo) * 2 > tolerance:
        mid = math.exp((math.log(upper_search_lo) + math.log(upper_search_hi)) / 2)
        val = sample(mid)
        if val is None:
            return None, None
        if val < target_db:
            upper_search_hi = mid  # above peak, below target → lower ceiling
        else:
            upper_search_lo = mid  # above target → raise floor

    f_high = math.exp((math.log(upper_search_lo) + math.log(upper_search_hi)) / 2)

    if create_graph:
        samples.sort(key=lambda x: x[0])
        freqs, dbs = zip(*samples)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.scatter(freqs, dbs, s=18, zorder=5, label="Samples")
        ax.plot(freqs, dbs, linewidth=1, alpha=0.6, label="Response")
        ax.axvline(
            f_low,
            color="blue",
            linewidth=1,
            linestyle="--",
            label=f"f_low = {f_low:,.1f} Hz",
        )
        ax.axvline(
            f_high,
            color="green",
            linewidth=1,
            linestyle="--",
            label=f"f_high = {f_high:,.1f} Hz",
        )
        ax.axvline(
            peak_freq,
            color="orange",
            linewidth=1,
            linestyle=":",
            label=f"f_peak = {peak_freq:,.1f} Hz",
        )
        ax.axhline(
            target_db,
            color="gray",
            linewidth=0.8,
            linestyle=":",
            label=f"{target_db:.1f} dB",
        )
        ax.set_xscale("log")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Attenuation (dB)")
        ax.set_title("Band-pass filter — Bode magnitude plot")
        ax.legend()
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        return (f_low, f_high), fig
    else:
        return (f_low, f_high), None
    

def find_notch_cutoff_frequencies(
    netlist_body: str,
    tolerance: float = 0.5,
    create_graph: bool = False,
) -> tuple[tuple[float, float] | None, plt.Figure | None]:
    """
    Find the lower and upper -3dB cutoff frequencies of a notch (band-stop)
    filter by binary searching over sampled attenuation values, and return a
    Bode magnitude plot of all sampled points.

    Assumes:
      - The filter has a single stopband notch with gain rolling off
        monotonically toward the notch on both sides and recovering
        monotonically away from it.
      - The passband reference is the passband gain found by probing decades
        away from the notch frequency.

    Not suitable for low-pass, high-pass, band-pass, or filters with
    stopband ripple.

    Parameters
    ----------
    netlist_body : str
        SPICE netlist fragment passed directly to simulate_attenuation.
    tolerance : float
        Stop bisecting when the bracket width is within this fraction of the
        midpoint frequency. Default 0.5. Increase for fewer samples and
        a rougher estimate; decrease for more precision.

    Returns
    -------
    tuple[tuple[float, float] | None, plt.Figure | None]
        - A (f_low, f_high) pair of -3dB cutoff frequencies in Hz,
          or None on any simulation failure.
        - A matplotlib Figure showing the Bode plot, or None on failure.
    """
    samples: list[tuple[float, float]] = []

    def sample(freq: float) -> float | None:
        val = simulate_attenuation(netlist_body, frequency=freq)
        if val is not None:
            samples.append((freq, val))
        return val

    # --- Step 1: Find the notch (stopband floor) by sweeping decades ---
    # Probe from 1 Hz to 1 GHz in decade steps, track the worst attenuation.
    probe_freqs = [10.0 ** e for e in range(0, 10)]  # 1 Hz → 1 GHz
    notch_db = math.inf
    notch_freq = None

    for freq in probe_freqs:
        val = sample(freq)
        if val is None:
            return None, None
        if val < notch_db:
            notch_db = val
            notch_freq = freq

    if notch_freq is None:
        return None, None

    # --- Step 2: Refine the notch with a ternary search in log-frequency space ---
    # We MINIMIZE gain (deepest notch), so invert the v1/v2 comparison vs. bandpass.
    lo = notch_freq / 10.0
    hi = notch_freq * 10.0
    for _ in range(12):
        width = (hi - lo) / (hi + lo) * 2
        if width < tolerance * 0.1:
            break
        m1 = math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) / 3)
        m2 = math.exp(math.log(lo) + 2 * (math.log(hi) - math.log(lo)) / 3)
        v1 = sample(m1)
        v2 = sample(m2)
        if v1 is None or v2 is None:
            return None, None
        # Keep the side that contains the lower value (deeper notch)
        if v1 > v2:
            lo = m1
        else:
            hi = m2
        # Update notch if we found something deeper
        for f, v in [(m1, v1), (m2, v2)]:
            if v < notch_db:
                notch_db = v
                notch_freq = f

    # The -3dB target is 3dB ABOVE the notch floor (gain recovers toward passband)
    target_db = notch_db + 3.0

    # Sanity check: passband at 1 Hz and 10 GHz must be above the target.
    # (If the filter attenuates everything, it's not a notch.)
    val_at_dc = sample(1.0)
    val_at_top = sample(1e10)
    if val_at_dc is None or val_at_top is None:
        return None, None
    if val_at_dc < target_db or val_at_top < target_db:
        # No clear passband on one or both sides — not a notch filter
        return None, None

    # --- Step 3: Binary search for the lower -3dB cutoff ---
    # Bracket: from 1 Hz (passband, above target) to notch_freq (below target).
    lower_search_lo = 1.0
    lower_search_hi = notch_freq

    while (lower_search_hi - lower_search_lo) / (lower_search_hi + lower_search_lo) * 2 > tolerance:
        mid = math.exp((math.log(lower_search_lo) + math.log(lower_search_hi)) / 2)
        val = sample(mid)
        if val is None:
            return None, None
        if val >= target_db:
            lower_search_lo = mid  # still in passband → raise floor toward notch
        else:
            lower_search_hi = mid  # entered stopband → lower ceiling

    f_low = math.exp((math.log(lower_search_lo) + math.log(lower_search_hi)) / 2)

    # --- Step 4: Binary search for the upper -3dB cutoff ---
    # Bracket: from notch_freq (below target) to 10 GHz (passband, above target).
    upper_search_lo = notch_freq
    upper_search_hi = 1e10

    while (upper_search_hi - upper_search_lo) / (upper_search_hi + upper_search_lo) * 2 > tolerance:
        mid = math.exp((math.log(upper_search_lo) + math.log(upper_search_hi)) / 2)
        val = sample(mid)
        if val is None:
            return None, None
        if val >= target_db:
            upper_search_hi = mid  # back in passband → lower ceiling toward notch
        else:
            upper_search_lo = mid  # still in stopband → raise floor

    f_high = math.exp((math.log(upper_search_lo) + math.log(upper_search_hi)) / 2)

    if create_graph:
        samples.sort(key=lambda x: x[0])
        freqs, dbs = zip(*samples)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.scatter(freqs, dbs, s=18, zorder=5, label="Samples")
        ax.plot(freqs, dbs, linewidth=1, alpha=0.6, label="Response")
        ax.axvline(
            f_low,
            color="blue",
            linewidth=1,
            linestyle="--",
            label=f"f_low = {f_low:,.1f} Hz",
        )
        ax.axvline(
            f_high,
            color="green",
            linewidth=1,
            linestyle="--",
            label=f"f_high = {f_high:,.1f} Hz",
        )
        ax.axvline(
            notch_freq,
            color="red",
            linewidth=1,
            linestyle=":",
            label=f"f_notch = {notch_freq:,.1f} Hz",
        )
        ax.axhline(
            target_db,
            color="gray",
            linewidth=0.8,
            linestyle=":",
            label=f"{target_db:.1f} dB (-3dB)",
        )
        ax.set_xscale("log")
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Attenuation (dB)")
        ax.set_title("Notch filter — Bode magnitude plot")
        ax.legend()
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        return (f_low, f_high), fig
    else:
        return (f_low, f_high), None