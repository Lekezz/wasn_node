"""
localize_capture.py

Estimate the direction a clap came from, using a real capture from the
board. This is the offline half of milestone 5: check_sync.py proves the
four channels are aligned, this one turns them into a bearing.

It reuses gcc_phat() and estimate_direction() from localization_sim.py
unchanged, so whatever this script reports is exactly what the reference
implementation produces. That matters because the CMSIS-DSP firmware port
will be validated against these same numbers.

Run:  python localize_capture.py [capture.npy] [--true-angle DEG]

The --true-angle option is for validation runs: give it the angle you
actually clapped from and it reports the error.
"""

import sys

import numpy as np

import array_geometry as geom
import localization_sim as ls

FS = ls.FS
C_SOUND = ls.C_SOUND

# Geometry comes from array_geometry.py so that trying a different array
# layout is a one-line change there, not an edit to this file.
MIC_POS = geom.active_positions()
ARRAY_MEASURED = geom.is_measured()

# Directions where the ACTIVE layout is unreliable. Near-square layouts
# (condition number close to 1) have none, so this is normally empty. The
# superseded 2.8 x 10 cm single-board rectangle had four, roughly 30 deg
# off the long axis, which is what this machinery was built for. A high
# condition number is the signal that blind cones exist at all.
POOR_CONES = [30, 150, 210, 330] if geom.describe(MIC_POS)["cond"] > 2.0 else []
POOR_HALF_WIDTH = 10            # degrees either side

WINDOW_BEFORE = 256
WINDOW_AFTER = 1792


def find_clap(cap):
    """Same transient locator check_sync.py uses, so both agree."""
    env = np.sum(np.abs(cap), axis=0)
    peak = int(np.argmax(env))
    noise = np.median(env)
    threshold = noise + 0.2 * (env[peak] - noise)
    onset = peak
    while onset > 0 and env[onset] > threshold:
        onset -= 1
    return onset, peak, float(env[peak] / max(noise, 1e-9))


def check_geometry(mic_pos):
    """
    Refuse to produce a confident answer from a badly posed array.

    Builds the same baseline matrix estimate_direction() solves and checks
    it actually spans two dimensions. A collinear array is rank 1: the
    across-axis component is unconstrained, and the reported angle
    collapses to 0 or 180 regardless of truth. Better to say so than to
    print a plausible looking number.
    """
    d = geom.describe(mic_pos)
    rank, cond = d["rank"], d["cond"]

    print(f"array geometry: {geom.ACTIVE}")
    for m, p in enumerate(mic_pos):
        print(f"  mic{m}: x {p[0]*100:+7.2f} cm   y {p[1]*100:+7.2f} cm")
    print(f"  span {d['span_x']*100:.2f} x {d['span_y']*100:.2f} cm, "
          f"aperture {d['aperture_m']*100:.1f} cm "
          f"({d['aperture_samples']:.1f} samples), "
          f"rank {rank} of 2, condition number {cond:.2f}")

    if rank < 2:
        print("  ERROR: the array is collinear. estimate_direction() cannot")
        print("  resolve the across-axis component and its output will be")
        print("  meaningless. Build a non-collinear array first.")
        return False
    if cond > 2.0:
        print(f"  WARNING: condition number {cond:.2f} is high. Accuracy will")
        print("  be strongly direction dependent, with blind directions.")
    if not ARRAY_MEASURED:
        print("  WARNING: this layout is not marked as measured, so the")
        print("  positions are nominal. Any bearing below is provisional.")
        print("  Measure port to port with calipers, put the numbers in")
        print("  array_geometry.py, and set measured=True for this layout.")
    print()
    return True


def localize(cap, onset, verbose=True):
    """Run GCC-PHAT on every pair and fuse into one bearing."""
    start = max(0, onset - WINDOW_BEFORE)
    stop = min(cap.shape[1], onset + WINDOW_AFTER)
    win = cap[:, start:stop].astype(np.float64)
    win -= win.mean(axis=1, keepdims=True)      # PHAT is a phase method

    saved = (ls.MIC_POS, ls.NUM_MICS, ls.PAIRS)
    try:
        ls.MIC_POS = MIC_POS
        ls.NUM_MICS = len(MIC_POS)
        ls.PAIRS = [(i, j) for i in range(ls.NUM_MICS)
                    for j in range(i + 1, ls.NUM_MICS)]

        pair_delays = {}
        if verbose:
            print(f"GCC-PHAT per pair over samples {start}..{stop}")
            print("  pair   delay (samples)   max physical   uses")
        for (i, j) in ls.PAIRS:
            spacing = np.linalg.norm(MIC_POS[j] - MIC_POS[i])
            max_tau = spacing / C_SOUND * FS
            # Sign convention matches localization_sim.run_trial exactly:
            # gcc_phat(a, b) returns (t_a - t_b), stored as (t_j - t_i).
            tau = -ls.gcc_phat(win[i], win[j], max_tau)
            pair_delays[(i, j)] = tau
            flag = "" if abs(tau) <= max_tau + 0.5 else "  <- EXCEEDS PHYSICS"
            if verbose:
                print(f"  {i}-{j}   {tau:+13.3f}   {max_tau:11.2f}"
                      f"   {spacing*100:5.1f} cm{flag}")

        bearing = ls.estimate_direction(pair_delays)
        return bearing, pair_delays
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved


def report_bearing(bearing, true_angle=None):
    b = bearing % 360
    print()
    print(f"ESTIMATED BEARING: {b:.1f} degrees")
    print("  (measured counterclockwise from +x, the long axis of the board,")
    print("   with +x pointing toward the mic0 / mic3 end)")

    for cone in POOR_CONES:
        if abs((b - cone + 180) % 360 - 180) <= POOR_HALF_WIDTH:
            print(f"  WARNING: this bearing is within {POOR_HALF_WIDTH} deg of "
                  f"{cone} deg, one of the four directions where this")
            print("  rectangular layout is unreliable (about 8 deg error in "
                  "simulation). Treat it as low confidence.")
            break

    if true_angle is not None:
        err = (b - true_angle + 180) % 360 - 180
        print(f"  true angle {true_angle:.1f} deg -> error {err:+.1f} deg")
    return b


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    true_angle = None
    if "--true-angle" in args:
        k = args.index("--true-angle")
        true_angle = float(args[k + 1])
        del args[k:k + 2]
    path = args[0] if args else "capture.npy"

    cap = np.load(path)
    if cap.ndim != 2 or cap.shape[0] != 4:
        raise SystemExit(f"expected a (4, nsamples) array, got {cap.shape}")
    cap = cap.astype(np.float64)
    print(f"loaded {path}: {cap.shape[0]} channels, {cap.shape[1]} samples "
          f"({cap.shape[1]/FS:.3f} s)\n")

    if not check_geometry(MIC_POS):
        raise SystemExit(1)

    onset, peak, ratio = find_clap(cap)
    print(f"transient at sample {peak} ({peak/FS:.3f} s), onset {onset}, "
          f"peak/noise {ratio:.1f}")
    if ratio < 20:
        print("  WARNING: weak transient. On the bring-up fixture a ratio of "
              "14.7 gave physically inconsistent delays while 327 gave clean "
              "ones. Clap harder and re-record.")
    print()

    bearing, _ = localize(cap, onset)
    report_bearing(bearing, true_angle)
