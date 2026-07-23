"""
plot_validation.py

The milestone 5 deliverable: estimated bearing versus true bearing for the
built array, from real claps at known angles.

How it finds your data:
  - Every file named angle<NNN>_capture.npy in this directory. The <NNN> is
    the true angle in degrees, which is exactly what
        python catch_audio4.py --tag angle045
    produces. So the normal workflow, clap at a measured angle with the
    matching --tag, then rerun this, needs no arguments.
  - Any extra points passed as PATH:ANGLE on the command line, e.g.
        python plot_validation.py captures/2026-07-23-square-clap/square_clap_4mic.npy:90
    which is how the already-archived 90 degree capture gets included
    without renaming it.

It always draws a SIMULATION reference curve for context: the same
estimator run on synthetic claps from the same geometry, with no room echo
and no measurement error. That line is the clean-room ceiling, NOT measured
data, and is labelled as such. Real points should sit near it but a few
degrees off. Do not confuse the two.

Output: validation_plot.png, plus a printed table.

Run:  python plot_validation.py [extra PATH:ANGLE ...]
"""

import glob
import os
import re
import sys

import numpy as np

import array_geometry as geom
import localization_sim as ls
import localize_capture as lc

FS = ls.FS


def _use_active_geometry():
    """Point the estimator at the built array and return a restore token."""
    saved = (ls.MIC_POS, ls.NUM_MICS, ls.PAIRS)
    ls.MIC_POS = geom.active_positions()
    ls.NUM_MICS = len(ls.MIC_POS)
    ls.PAIRS = geom.pairs(ls.NUM_MICS)
    return saved


def bearing_of(cap):
    """Estimated bearing (deg, 0..360) for a (4, N) capture array."""
    onset, _, _ = lc.find_clap(cap.astype(float))
    b, _ = lc.localize(cap.astype(float), onset, verbose=False)
    return b % 360


def measured_points(extra):
    """
    (true, estimated, error) for every real capture we can find.

    error is wrapped to [-180, 180]. extra is a list of PATH:ANGLE strings.
    """
    found = {}                       # path -> true angle, dedup by path

    for path in sorted(glob.glob("angle*_capture.npy")):
        m = re.search(r"angle(\d+)", os.path.basename(path))
        if m:
            found[os.path.abspath(path)] = float(m.group(1))

    for item in extra:
        if ":" not in item:
            print(f"  skipping '{item}': expected PATH:ANGLE")
            continue
        path, ang = item.rsplit(":", 1)
        if not os.path.exists(path):
            print(f"  skipping '{path}': file not found")
            continue
        found[os.path.abspath(path)] = float(ang)

    rows = []
    saved = _use_active_geometry()
    try:
        for path, true in sorted(found.items(), key=lambda kv: kv[1]):
            cap = np.load(path)
            if cap.ndim != 2 or cap.shape[0] != 4:
                print(f"  skipping '{path}': shape {cap.shape} is not (4, N)")
                continue
            est = bearing_of(cap)
            err = (est - true + 180) % 360 - 180
            rows.append((true, est, err, os.path.basename(path)))
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved
    return rows


def sim_reference(step=5, trials=3):
    """Simulation estimated-vs-true sweep on the active geometry."""
    saved = _use_active_geometry()
    trues, ests, errs = [], [], []
    seed = 0
    try:
        for true in np.arange(0, 360, step):
            e = []
            for _ in range(trials):
                sigs, _ = ls.simulate_capture(true, n_samples=4096, seed=seed)
                seed += 1
                cap = sigs / np.abs(sigs).max() * 12000
                e.append(bearing_of(cap))
            # average as unit vectors so the wrap at 360/0 does not bite
            ang = np.radians(e)
            mean = np.degrees(np.arctan2(np.sin(ang).mean(),
                                         np.cos(ang).mean())) % 360
            trues.append(true)
            ests.append(mean)
            errs.append((mean - true + 180) % 360 - 180)
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved
    return np.array(trues), np.array(ests), np.array(errs)


def main(extra):
    rows = measured_points(extra)
    st, se, serr = sim_reference()

    print(f"array: {geom.ACTIVE}  (condition number "
          f"{geom.describe(geom.active_positions())['cond']:.2f})")
    print(f"simulation reference: mean |error| {np.abs(serr).mean():.2f} deg, "
          f"worst {np.abs(serr).max():.2f} deg\n")

    if rows:
        print("measured claps")
        print("  true    estimated    error    file")
        for true, est, err, name in rows:
            print(f"  {true:5.1f}   {est:8.1f}   {err:+6.2f}   {name}")
        me = np.array([r[2] for r in rows])
        print(f"\n  measured mean |error| {np.abs(me).mean():.2f} deg over "
              f"{len(rows)} clap(s), worst {np.abs(me).max():.2f} deg")
    else:
        print("no measured captures found yet. Do the sweep:")
        print("  for each known angle A: python catch_audio4.py --tag angleA")
        print("  then rerun this script.")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not installed, no PNG written "
              "(pip install matplotlib).")
        return

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 5))

    # Left: estimated vs true, with the ideal y = x line.
    axL.plot([0, 360], [0, 360], "k--", lw=1, alpha=0.6, label="ideal (y = x)")
    axL.plot(st, se, "-", color="tab:blue", alpha=0.7,
             label="simulation (clean-room reference)")
    if rows:
        t = [r[0] for r in rows]
        e = [r[1] for r in rows]
        axL.scatter(t, e, s=90, color="tab:red", zorder=5,
                    edgecolor="black", linewidth=0.6,
                    label=f"measured claps (n={len(rows)})")
    axL.set_xlabel("true angle (deg)")
    axL.set_ylabel("estimated bearing (deg)")
    axL.set_title("Estimated vs true bearing")
    axL.set_xlim(0, 360)
    axL.set_ylim(0, 360)
    axL.set_xticks(range(0, 361, 45))
    axL.set_yticks(range(0, 361, 45))
    axL.grid(alpha=0.3)
    axL.legend(loc="upper left", fontsize=9)

    # Right: signed error vs true angle.
    axR.axhline(0, color="k", lw=1, alpha=0.6)
    axR.plot(st, serr, "-", color="tab:blue", alpha=0.7,
             label="simulation")
    axR.fill_between(st, serr, 0, color="tab:blue", alpha=0.1)
    if rows:
        t = [r[0] for r in rows]
        er = [r[2] for r in rows]
        axR.scatter(t, er, s=90, color="tab:red", zorder=5,
                    edgecolor="black", linewidth=0.6, label="measured")
    axR.set_xlabel("true angle (deg)")
    axR.set_ylabel("error (deg)")
    axR.set_title("Error vs true angle")
    axR.set_xlim(0, 360)
    axR.set_xticks(range(0, 361, 45))
    axR.grid(alpha=0.3)
    axR.legend(loc="upper right", fontsize=9)

    fig.suptitle(f"4-mic bearing validation, {geom.ACTIVE}", fontsize=13)
    fig.tight_layout()
    out = "validation_plot.png"
    fig.savefig(out, dpi=130)
    print(f"\nwrote {out}")
    if len(rows) < 2:
        print("NOTE: with fewer than two measured claps the red points are a "
              "spot check, not the deliverable. The blue line is simulation, "
              "not data. Do the angle sweep to fill in the measured series.")


if __name__ == "__main__":
    main(sys.argv[1:])
