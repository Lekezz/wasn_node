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

import array_geometry as geom
import localization_sim as ls

FS = ls.FS
C_SOUND = ls.C_SOUND

# Every layout registered in array_geometry.py, so adding one there gets it
# scored here automatically. Extra one-off candidates can go in EXTRAS
# without cluttering the real registry.
CANDIDATES = {name: (spec["positions"], spec["note"])
              for name, spec in geom.LAYOUTS.items()}

EXTRAS = {
    "9.0 cm square": (geom.rect(0.090, 0.090),
                      "square that fits the glued pair, for comparison"),
    "2.5 cm square": (geom.rect(0.025, 0.025),
                      "what a single board allowed in both axes"),
}
CANDIDATES.update(EXTRAS)


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

    print("\nnotes")
    for (name, *_ , fits) in rows:
        print(f"  {name:<32} {fits}")

    # Blind direction check on the ACTIVE layout. A near-square array
    # (condition number close to 1) should have no direction that is much
    # worse than the rest; a long thin one will. This is the check that
    # decides whether validation claps need to avoid certain bearings.
    pos = geom.active_positions()
    d = geom.describe(pos)
    print(f"\nblind direction check on ACTIVE layout ({geom.ACTIVE}, "
          f"condition number {d['cond']:.2f})")
    saved = (ls.MIC_POS, ls.NUM_MICS, ls.PAIRS)
    try:
        ls.MIC_POS = pos
        ls.NUM_MICS = len(pos)
        ls.PAIRS = [(i, j) for i in range(ls.NUM_MICS)
                    for j in range(i + 1, ls.NUM_MICS)]
        per_angle, seed = [], 2000
        for ang in range(0, 360, 15):
            errs = [abs(ls.run_trial(ang, seed=seed + k, verbose=False))
                    for k in range(4)]
            seed += 4
            per_angle.append((float(np.mean(errs)), ang))
        per_angle.sort(reverse=True)
        best = per_angle[-1]
        print("  worst 4 directions: " +
              ", ".join(f"{a} deg = {m:.2f}" for m, a in per_angle[:4]))
        print(f"  best direction:     {best[1]} deg = {best[0]:.2f}")
        spread = per_angle[0][0] / max(best[0], 1e-6)
        if per_angle[0][0] < 3.0:
            print("  VERDICT: no blind directions. Validation claps can be "
                  "taken from any bearing.")
        else:
            print(f"  VERDICT: worst direction is {per_angle[0][0]:.1f} deg "
                  f"({spread:.0f}x the best). Avoid those bearings when "
                  f"planning validation claps.")
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved
