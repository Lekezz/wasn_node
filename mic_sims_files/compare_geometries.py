"""
compare_geometries.py

Which array layout should we actually build?

The 10 cm square the simulation was validated against does not fit on a
single solderless breadboard: a full-size 830-point board is about 16.5 cm
long but only about 2.8 cm across the usable terminal rows (row A to row J,
spanning the centre channel). This script scores the layouts that DO fit,
plus some that need a bigger mounting surface, so the geometry decision is
made on numbers instead of guesswork.

It does not modify localization_sim.py. It imports it and swaps the module
level geometry for each candidate, so the estimator under test is exactly
the reference implementation.

IMPORTANT: these are simulation numbers. No reverberation, no mic self
noise mismatch, no position measurement error, and the estimator is told
the true geometry exactly. Real world error will be several times worse.
Use these to RANK layouts against each other, not to predict absolute
accuracy.

Run:  python compare_geometries.py
"""

import numpy as np

import localization_sim as ls

FS = ls.FS
C_SOUND = ls.C_SOUND

# Candidate layouts, all in metres, (x, y) per mic.
# "fits" describes the mounting surface each one needs.
CANDIDATES = {}


def square(side):
    h = side / 2.0
    return np.array([[h, h], [-h, h], [-h, -h], [h, -h]])


def rect(width, height):
    w, h = width / 2.0, height / 2.0
    return np.array([[w, h], [-w, h], [-w, -h], [w, -h]])


CANDIDATES["10 cm square (validated reference)"] = (
    square(0.10), "needs a separate flat substrate, will not fit a breadboard")
CANDIDATES["2.5 cm square"] = (
    square(0.025), "fits one breadboard, very tight")
CANDIDATES["2.8 x 10 cm rectangle"] = (
    rect(0.10, 0.028), "fits one full-size breadboard")
CANDIDATES["2.8 x 15 cm rectangle"] = (
    rect(0.15, 0.028), "fits one full-size breadboard, near full length")
CANDIDATES["5 cm square"] = (
    square(0.05), "needs two breadboards clipped together, or a substrate")
CANDIDATES["10 cm L-shape"] = (
    np.array([[0.0, 0.0], [0.10, 0.0], [0.0, 0.10], [0.05, 0.05]]),
    "needs a separate flat substrate")


def score(mic_pos, n_angles=36, trials_per_angle=3, snr_db=20.0):
    """
    Sweep a source around the array and return angle error statistics.

    Swaps the geometry into localization_sim so the estimator being scored
    is the reference implementation, then restores it.
    """
    saved_pos, saved_n, saved_pairs = ls.MIC_POS, ls.NUM_MICS, ls.PAIRS
    try:
        ls.MIC_POS = mic_pos
        ls.NUM_MICS = len(mic_pos)
        ls.PAIRS = [(i, j) for i in range(ls.NUM_MICS)
                    for j in range(i + 1, ls.NUM_MICS)]

        errors = []
        seed = 0
        for ang in np.linspace(0, 360, n_angles, endpoint=False):
            for _ in range(trials_per_angle):
                errors.append(ls.run_trial(ang, seed=seed, verbose=False))
                seed += 1
        return np.abs(np.array(errors))
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved_pos, saved_n, saved_pairs


def aperture(mic_pos):
    """Largest mic-to-mic distance, and that distance in samples of delay."""
    d = max(np.linalg.norm(mic_pos[i] - mic_pos[j])
            for i in range(len(mic_pos)) for j in range(i + 1, len(mic_pos)))
    return d, d / C_SOUND * FS


if __name__ == "__main__":
    print("Geometry comparison, simulation only (see the caveat in the "
          "docstring)")
    print(f"FS {FS} Hz, source at 2 m, 20 dB SNR, 36 angles x 3 trials\n")

    rows = []
    for name, (pos, fits) in CANDIDATES.items():
        err = score(pos)
        ap_m, ap_samp = aperture(pos)
        rows.append((name, ap_m, ap_samp, err.mean(), np.median(err),
                     np.percentile(err, 90), err.max(), fits))

    hdr = (f"{'layout':<32} {'aperture':>9} {'samples':>8} "
           f"{'mean':>7} {'median':>7} {'p90':>7} {'worst':>8}")
    print(hdr)
    print("-" * len(hdr))
    for (name, ap_m, ap_samp, mean, med, p90, worst, _) in rows:
        print(f"{name:<32} {ap_m*100:8.1f}cm {ap_samp:8.2f} "
              f"{mean:6.2f}d {med:6.2f}d {p90:6.2f}d {worst:7.2f}d")

    print("\nmounting requirement")
    for (name, *_ , fits) in rows:
        print(f"  {name:<32} {fits}")

    # Anisotropy check: a long thin rectangle should be much better at some
    # angles than others. Report error split by whether the source is near
    # the long axis (endfire) or perpendicular to it (broadside).
    print("\nanisotropy: mean error broadside vs endfire (long-axis layouts)")
    for name in ("2.8 x 10 cm rectangle", "2.8 x 15 cm rectangle",
                 "10 cm square (validated reference)"):
        pos = CANDIDATES[name][0]
        saved = (ls.MIC_POS, ls.NUM_MICS, ls.PAIRS)
        try:
            ls.MIC_POS = pos
            ls.NUM_MICS = len(pos)
            ls.PAIRS = [(i, j) for i in range(4) for j in range(i + 1, 4)]
            broad, end, seed = [], [], 1000
            for ang in (75, 90, 105, 255, 270, 285):      # near +/- y
                for _ in range(3):
                    broad.append(abs(ls.run_trial(ang, seed=seed,
                                                  verbose=False)))
                    seed += 1
            for ang in (0, 15, 345, 165, 180, 195):       # near +/- x
                for _ in range(3):
                    end.append(abs(ls.run_trial(ang, seed=seed,
                                                verbose=False)))
                    seed += 1
            print(f"  {name:<32} broadside {np.mean(broad):6.2f} deg   "
                  f"endfire {np.mean(end):6.2f} deg")
        finally:
            ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved
