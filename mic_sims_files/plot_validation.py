"""
plot_validation.py

The milestone 5 deliverable: estimated bearing versus true bearing for the
built array, from real claps at known angles.

How it finds your data:
  - Every trial under captures/<session>/angle<NNN>/trial<K>.npy, which is
    exactly what
        python catch_audio4.py --tag angle045 --trials 5
    produces, plus any legacy loose angle<NNN>_trial<K>_capture.npy left in
    this directory. Trials are grouped by angle: each angle gets a mean
    bearing and a spread across its trials. So the normal workflow, sweep
    several angles with several trials each, then rerun this, needs no
    arguments.
  - Pass --session NAME to plot one session only. Do that whenever you have
    moved the array, because captures taken in a different room setup have
    a different echo environment and are not more samples of the same thing.
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

Run:  python plot_validation.py [--session NAME] [extra PATH:ANGLE ...]
"""

import os
import sys

import numpy as np

import array_geometry as geom
import capture_paths as cp
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


def measured_trials(extra, only_session=None):
    """
    Per-trial results grouped by true angle.

    Returns a list of dicts, one per true angle, sorted by angle:
        {"true", "errors" (list), "ests" (list), "n"}
    error is wrapped to [-180, 180]. extra is a list of PATH:ANGLE strings.
    only_session limits the plot to one captures/ session folder, which is
    what you want after moving the array: a sweep recorded against a different
    room is different data, not more of the same.
    """
    found = {}                       # path -> true angle, dedup by path

    # Every angled capture on disk: the captures/<session>/angle<NNN>/ layout
    # plus any legacy loose files. capture_paths owns both forms so this
    # script does not have to know the layout.
    for d in cp.find_captures(session=only_session):
        found[d["path"]] = d["angle"]

    for item in extra:
        if ":" not in item:
            print(f"  skipping '{item}': expected PATH:ANGLE")
            continue
        path, ang = item.rsplit(":", 1)
        if not os.path.exists(path):
            print(f"  skipping '{path}': file not found")
            continue
        found[os.path.abspath(path)] = float(ang)

    by_angle = {}
    saved = _use_active_geometry()
    try:
        for path, true in sorted(found.items(), key=lambda kv: kv[1]):
            cap = np.load(path)
            if cap.ndim != 2 or cap.shape[0] != 4:
                print(f"  skipping '{path}': shape {cap.shape} is not (4, N)")
                continue
            est = bearing_of(cap)
            err = (est - true + 180) % 360 - 180
            g = by_angle.setdefault(true, {"true": true, "ests": [],
                                           "errors": []})
            g["ests"].append(est)
            g["errors"].append(err)
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved

    groups = []
    for true in sorted(by_angle):
        g = by_angle[true]
        g["n"] = len(g["errors"])
        groups.append(g)
    return groups


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


def main(extra, only_session=None):
    groups = measured_trials(extra, only_session)
    st, se, serr = sim_reference()

    print(f"array: {geom.ACTIVE}  (condition number "
          f"{geom.describe(geom.active_positions())['cond']:.2f})")
    print(f"session: {only_session or 'all sessions'}")
    print(f"simulation reference: mean |error| {np.abs(serr).mean():.2f} deg, "
          f"worst {np.abs(serr).max():.2f} deg\n")

    total_trials = sum(g["n"] for g in groups)
    if groups:
        print("measured claps, grouped by true angle")
        print("  true   trials   mean err   std (spread)   mean|err|   max|err|")
        all_abs = []
        for g in groups:
            err = np.array(g["errors"])
            all_abs.append(np.abs(err))
            print(f"  {g['true']:5.1f}    {g['n']:3d}    "
                  f"{err.mean():+6.2f}     {err.std():6.2f}       "
                  f"{np.abs(err).mean():6.2f}     {np.abs(err).max():6.2f}")
        all_abs = np.concatenate(all_abs)
        spreads = [np.array(g["errors"]).std() for g in groups if g["n"] > 1]
        print(f"\n  {len(groups)} angle(s), {total_trials} clap(s) total")
        print(f"  accuracy: mean |error| {all_abs.mean():.2f} deg, "
              f"worst {all_abs.max():.2f} deg")
        if spreads:
            print(f"  precision: mean trial-to-trial spread (std) "
                  f"{np.mean(spreads):.2f} deg")
    else:
        print("no measured captures found yet. Do the sweep:")
        print("  per angle A: python catch_audio4.py --tag angleA --trials 5")
        print("  then rerun this script.")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not installed, no PNG written "
              "(pip install matplotlib).")
        return

    # Per-angle summary arrays for the mean markers and error bars.
    g_true = np.array([g["true"] for g in groups])
    g_mean_err = np.array([np.mean(g["errors"]) for g in groups])
    g_std_err = np.array([np.std(g["errors"]) for g in groups])
    g_mean_est = g_true + g_mean_err            # avoids the 360/0 wrap

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 5))

    # Left: estimated vs true. Faint individual trials, bold per-angle mean
    # with +/- 1 std error bars, ideal line, simulation reference.
    axL.plot([0, 360], [0, 360], "k--", lw=1, alpha=0.6, label="ideal (y = x)")
    axL.plot(st, se, "-", color="tab:blue", alpha=0.6,
             label="simulation (clean-room)")
    for g in groups:                            # every trial, faint
        axL.scatter([g["true"]] * g["n"], g["ests"], s=22,
                    color="tab:red", alpha=0.35, zorder=3)
    if len(groups):
        axL.errorbar(g_true, g_mean_est, yerr=g_std_err, fmt="o",
                     color="tab:red", ms=7, capsize=4, zorder=5,
                     markeredgecolor="black", markeredgewidth=0.6,
                     label=f"measured mean +/- std (n={total_trials})")
    axL.set_xlabel("true angle (deg)")
    axL.set_ylabel("estimated bearing (deg)")
    axL.set_title("Estimated vs true bearing")
    axL.set_xlim(0, 360)
    axL.set_ylim(0, 360)
    axL.set_xticks(range(0, 361, 45))
    axL.set_yticks(range(0, 361, 45))
    axL.grid(alpha=0.3)
    axL.legend(loc="upper left", fontsize=9)

    # Right: signed error vs true angle, same layering.
    axR.axhline(0, color="k", lw=1, alpha=0.6)
    axR.plot(st, serr, "-", color="tab:blue", alpha=0.5, label="simulation")
    axR.fill_between(st, serr, 0, color="tab:blue", alpha=0.1)
    for g in groups:
        axR.scatter([g["true"]] * g["n"], g["errors"], s=22,
                    color="tab:red", alpha=0.35, zorder=3)
    if len(groups):
        axR.errorbar(g_true, g_mean_err, yerr=g_std_err, fmt="o",
                     color="tab:red", ms=7, capsize=4, zorder=5,
                     markeredgecolor="black", markeredgewidth=0.6,
                     label="measured mean +/- std")
    axR.set_xlabel("true angle (deg)")
    axR.set_ylabel("error (deg)")
    axR.set_title("Error vs true angle")
    axR.set_xlim(0, 360)
    axR.set_xticks(range(0, 361, 45))
    axR.grid(alpha=0.3)
    axR.legend(loc="upper right", fontsize=9)

    fig.suptitle(f"4-mic bearing validation, {geom.ACTIVE}  "
                 f"({len(groups)} angles, {total_trials} claps)", fontsize=13)
    fig.tight_layout()
    out = "validation_plot.png"
    fig.savefig(out, dpi=130)
    print(f"\nwrote {out}")
    thin = [g["true"] for g in groups if g["n"] < 2]
    if thin:
        print(f"NOTE: angle(s) {thin} have only one trial, so their error bar "
              "is zero and is not real spread. Aim for 5+ trials per angle.")
    if total_trials and len(groups) < 2:
        print("NOTE: the blue line is simulation, not data. One angle is a "
              "spot check; sweep several to make the deliverable.")


if __name__ == "__main__":
    argv = sys.argv[1:]
    session = None
    if "--session" in argv:
        k = argv.index("--session")
        session = argv[k + 1]
        del argv[k:k + 2]
    main(argv, session)
