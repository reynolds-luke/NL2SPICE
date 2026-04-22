import subprocess
import tempfile
import os
import re
import math

NGSPICE_EXE = "ngspice"

def simulate_attenuation(netlist_body: str, frequency: float) -> float | None:
    """
    Run an ngspice AC simulation and return the attenuation at VOUT (in dB).

    Parameters
    ----------
    netlist_body : str
        SPICE netlist fragment containing only the circuit elements and .param
        lines (no title line, no .AC/.PRINT/.END). Must define nodes VIN and VOUT.
    frequency : float
        Frequency (Hz) at which to evaluate the gain/attenuation.

    Returns
    -------
    float | None
        Attenuation in dB at the requested frequency, or None on any failure.
    """
    body_upper = netlist_body.upper()
    if "VIN" not in body_upper or "VOUT" not in body_upper:
        return None

    cleaned = "\n".join(
        line for line in netlist_body.splitlines()
        if not line.strip().startswith(".")
    )

    netlist = (
        "* Auto-generated AC simulation\n"
        + cleaned.strip()
        + f"\n.AC LIN 1 {frequency} {frequency}\n"
        ".PRINT AC VM(VOUT)\n"
        ".END\n"
    )

    # Unique temp files per call — safe for concurrent multiprocessing workers.
    netlist_fd, netlist_path = tempfile.mkstemp(suffix=".cir", prefix="sim_attn_")
    output_fd,  output_path  = tempfile.mkstemp(suffix=".txt", prefix="sim_attn_")
    os.close(netlist_fd)
    os.close(output_fd)

    try:
        with open(netlist_path, "w") as f:
            f.write(netlist)

        result = subprocess.run(
            [NGSPICE_EXE, "-b", "-o", output_path, netlist_path],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    finally:
        try:
            os.unlink(netlist_path)
        except OSError:
            pass

    try:
        with open(output_path, "rb") as f:
            raw = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return None
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass

    for line in raw.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 3:
            try:
                mag = float(parts[2])
                return 20 * math.log10(abs(mag))
            except (ValueError, ZeroDivisionError):
                continue

    return None