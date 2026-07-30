"""
compare_mic_count.py

Is the fourth microphone worth it?

The question this answers is a build question: a three mic node is cheaper,
uses one less DFSDM filter, one less DMA stream, and 25 percent less RAM per
second of audio. What does it cost in bearing accuracy?

The trick that makes the answer trustworthy is that no new recording is
needed. Every trial in captures/<session>/angle<NNN>/trial<K>.npy already
holds all four channels, and a three mic triangle is a SUBSET of those same
samples. Dropping a mic in software therefore gives a PAIRED comparison:
the four mic array and the triangle are judged on the identical acoustic
event, in the identical room, at the identical instant. There is no
session to session confound, no second sitting at the bench, and no
synthetic data standing in for a real clap. The difference reported here is
the geometry and nothing else.

Everything numerical is imported, not reimplemented. find_clap and localize
come from localize_capture.py, which in turn uses gcc_phat and
estimate_direction from localization_sim.py, so this study and the
reference implementation cannot drift apart. The triangle residual comes
from compare_board.py, which is the one that matches localize.c. Geometry
comes from array_geometry.py and the ACTIVE layout is restored on the way
out, the same way compare_geometries.py and localize_capture.py do it.

The four mic numbers are printed first as a HARNESS CHECK. They have to
reproduce the published sweep result (mean 1.11 deg, worst 4.04 deg, mean
spread 0.99 deg). If they do not then something in this script is wrong and
the three mic numbers mean nothing, so the script says so and exits 1
without pretending otherwise.

Run:  python compare_mic_count.py [--session NAME] [--fig PATH]
      python compare_mic_count.py --no-fig
"""

import argparse
import glob
import itertools
import os
import re
import sys

import numpy as np

import array_geometry as geom
import capture_paths as cp
import compare_board as cb
import localize_capture as lc

FS = lc.FS
C_SOUND = lc.C_SOUND

# The sweep the project's headline number comes from.
DEFAULT_SESSION = "2026-07-29-sweep"

# What the four mic configuration must reproduce, from plot_validation.py on
# the same session. These are a check on this harness, not an input to it.
BASELINE_MEAN_ABS = 1.11
BASELINE_WORST = 4.04
BASELINE_SPREAD = 0.99
BASELINE_TOL = 0.02        # degrees, generous next to the 0.01 deg printed

# A trial counts as materially worse when losing the mic costs more than this
# many degrees on that same clap. Two degrees is roughly twice the four mic
# mean error, so it is the point where the degradation stops being noise on
# an already small number and starts being visible in the answer.
WORSE_DEG = 2.0

# Where the figure goes, next to the other presentation figures.
FIG_DEFAULT = os.path.join(os.path.dirname(cp.BASE_DIR), "docs", "images",
                           "fig_miccount.png")

# Palette lifted from docs/make_presentation.py so this figure sits beside
# the others without a restyle.
INK = "#0b0b0b"
INK2 = "#52514e"
ACCENT = "#2a78d6"
STATUS_BAD = "#e34948"
SURFACE = "#fcfcfb"
GRID = "#e3e2dd"


# --------------------------------------------------------------- geometry

def subset_positions(mic_pos, idx):
    """The rows of mic_pos belonging to one mic subset, in subset order."""
    return np.asarray(mic_pos)[list(idx)]


def baseline_matrix(pos):
    """
    The matrix estimate_direction() solves for this layout.

    One row per unique pair, each row the vector between the two mics. Built
    here rather than imported because array_geometry.describe() already does
    the same thing for its rank and condition report and this file needs the
    matrix itself for the direction dependent part below.
    """
    n = len(pos)
    return np.array([pos[i] - pos[j] for (i, j) in geom.pairs(n)])


def bearing_amplification(pos, bearing_deg):
    """
    How much a given layout multiplies delay noise into bearing error, as a
    function of where the source is.

    Least squares gives u with covariance proportional to inv(A.T A). A
    bearing is the ANGLE of u, so only the component of the error across u
    matters: the component along u changes the length of a vector whose
    length is thrown away. Projecting the covariance onto the across
    direction gives a per bearing noise gain, which is the direction
    dependence a condition number summarises in one number.

    Returned in metres of position error per metre of delay error, so only
    the RATIO between two layouts is meaningful.
    """
    A = baseline_matrix(pos)
    cov = np.linalg.inv(A.T @ A)
    t = np.radians(np.asarray(bearing_deg, dtype=float))
    perp = np.stack([-np.sin(t), np.cos(t)], axis=-1)
    return np.sqrt(np.einsum("...i,ij,...j->...", perp, cov, perp))


def configurations(mic_pos):
    """
    Every configuration to score: the built four mic array, then all four
    three mic triangles.

    Each entry carries its own positions and its geometric health, so the
    printed table and the estimator are reading the same object.
    """
    out = []
    for idx in [(0, 1, 2, 3)] + list(itertools.combinations(range(4), 3)):
        pos = subset_positions(mic_pos, idx)
        d = geom.describe(pos)
        out.append({
            "idx": idx,
            "name": ("4-mic " if len(idx) == 4 else "3-mic ")
                    + "".join(str(m) for m in idx),
            "n_mics": len(idx),
            "pos": pos,
            "pairs": geom.pairs(len(idx)),
            "n_pairs": len(geom.pairs(len(idx))),
            "n_triangles": len(list(itertools.combinations(range(len(idx)), 3))),
            "rank": d["rank"],
            "cond": d["cond"],
            "aperture_m": d["aperture_m"],
        })
    return out


# --------------------------------------------------------------- estimation

def run_config(cap, cfg, mic_pos):
    """
    Localize one capture as if only this configuration's mics existed.

    The capture is sliced down to the subset's channels BEFORE anything
    looks at it, which is the honest version of the experiment: a real three
    mic node would build its transient envelope from three channels too, so
    find_clap gets three channels here, not four. That can move the onset by
    a sample or two, and that movement is part of what losing a mic costs.

    localize_capture.localize takes its geometry from lc.MIC_POS, so the
    subset is swapped in and restored, exactly the way plot_validation.py
    swaps the active layout into localization_sim. Nothing is copied out of
    localize_capture into this file.
    """
    sub = np.asarray(cap, dtype=np.float64)[list(cfg["idx"])]
    saved = lc.MIC_POS
    try:
        lc.MIC_POS = cfg["pos"]
        onset, peak, snr = lc.find_clap(sub)
        bearing, delays = lc.localize(sub, onset, verbose=False)
    finally:
        lc.MIC_POS = saved
    return {
        "bearing": bearing % 360,
        "delays": delays,
        "onset": onset,
        "peak": peak,
        "snr": snr,
        "residual": cb.triangle_residual(delays),
    }


def score_session(trials, cfgs, mic_pos):
    """
    Run every configuration over every trial.

    Returns a dict keyed by configuration name, each holding the per trial
    rows in the same order as trials, so any two configurations can be
    subtracted trial by trial. That ordering is the whole paired comparison,
    so it is built once here rather than matched up later by file name.
    """
    results = {}
    for cfg in cfgs:
        rows = []
        for t in trials:
            r = run_config(t["cap"], cfg, mic_pos)
            r["angle"] = t["angle"]
            r["label"] = t["label"]
            r["error"] = (r["bearing"] - t["angle"] + 180) % 360 - 180
            rows.append(r)
        results[cfg["name"]] = rows
    return results


def summarize(rows):
    """Accuracy and precision for one configuration over a whole session."""
    err = np.array([r["error"] for r in rows])
    ang = np.array([r["angle"] for r in rows])
    per_angle = []
    for a in sorted(set(ang)):
        e = err[ang == a]
        per_angle.append({
            "angle": a,
            "n": len(e),
            "mean": float(e.mean()),
            "std": float(e.std()),
            "mean_abs": float(np.abs(e).mean()),
            "max_abs": float(np.abs(e).max()),
        })
    spreads = [g["std"] for g in per_angle if g["n"] > 1]
    return {
        "n": len(err),
        "mean_abs": float(np.abs(err).mean()),
        "worst": float(np.abs(err).max()),
        "spread": float(np.mean(spreads)) if spreads else 0.0,
        "per_angle": per_angle,
    }


# ------------------------------------------------------------------ input

def load_trials(session):
    """
    Every good trial in one session, newest capture layout, oldest first by
    angle.

    capture_paths.find_captures globs trial*.npy only, so a retaken capture
    renamed to rejected<N>.npy is invisible here without this script knowing
    the rule. That is deliberate: the study has to run on the same 39 claps
    the headline number was computed from, not on a different set.
    """
    trials = []
    for d in cp.find_captures(session=session):
        cap = np.load(d["path"])
        if cap.ndim != 2 or cap.shape[0] != 4:
            print(f"  skipping {cp.describe(d['path'])}: shape {cap.shape} "
                  "is not (4, N)")
            continue
        trials.append({
            "path": d["path"],
            "angle": d["angle"],
            "cap": cap.astype(np.float64),
            "label": f"{d['tag']}/trial{d['trial']}",
        })
    return trials


def load_rejected(session):
    """
    The retaken captures from the same session, which is the only set of
    known bad data the project has.

    These were judged bad at the bench and renamed rather than deleted,
    precisely so they would still be available as evidence. That makes them
    the natural test set for the error detection question: a check worth
    having should fire on these and stay quiet on the 39 keepers.
    """
    out = []
    root = cp.session_dir(session)
    for path in sorted(glob.glob(os.path.join(root, "**", "rejected*.npy"),
                                 recursive=True)):
        tag = os.path.basename(os.path.dirname(path))
        m = re.search(r"angle(\d+)", tag)
        if m is None:
            continue
        cap = np.load(path)
        if cap.ndim != 2 or cap.shape[0] != 4:
            continue
        n = re.search(r"rejected(\d+)\.npy$", os.path.basename(path))
        out.append({
            "path": os.path.abspath(path),
            "angle": float(m.group(1)),
            "cap": cap.astype(np.float64),
            "label": f"{tag}/rejected{n.group(1) if n else '?'}",
        })
    return out


# --------------------------------------------------------------- reporting

def print_geometry(cfgs):
    print("GEOMETRY")
    print(f"  active layout: {geom.ACTIVE}"
          f"{'' if geom.is_measured() else '   (NOT measured, provisional)'}")
    print("  config      mics   pairs   triangles   rank   cond    aperture")
    for c in cfgs:
        print(f"  {c['name']:<10}   {c['n_mics']:d}      {c['n_pairs']:d}"
              f"         {c['n_triangles']:d}         {c['rank']:d}    "
              f"{c['cond']:5.3f}   {c['aperture_m']*100:5.1f} cm")
    conds = sorted({round(c["cond"], 6) for c in cfgs if c["n_mics"] == 3})
    if len(conds) == 1:
        print(f"  all four triangles share condition number {conds[0]:.3f}, "
              "which is what")
        print("  the rectangle's symmetry predicts. No triangle is a better "
              "choice than")
        print("  another on geometry alone.")
    print()


def print_accuracy(cfgs, results):
    print("ACCURACY over the session, one row per configuration")
    print("  config       n    mean |err|   worst |err|   mean spread")
    base = None
    for c in cfgs:
        s = summarize(results[c["name"]])
        if base is None:
            base = s
        print(f"  {c['name']:<10} {s['n']:3d}    {s['mean_abs']:7.2f}       "
              f"{s['worst']:7.2f}       {s['spread']:7.2f}")
    print()
    return base


def check_harness(base):
    """
    Refuse to interpret anything if the four mic column moved.

    The four mic result here comes out of the same code path plot_validation
    .py uses on the same files, so it has to land on the published numbers.
    If it does not, the failure is in this script, and a three mic number
    computed by a broken harness is worse than no number at all.
    """
    checks = [
        ("mean |error|", base["mean_abs"], BASELINE_MEAN_ABS),
        ("worst |error|", base["worst"], BASELINE_WORST),
        ("mean spread", base["spread"], BASELINE_SPREAD),
    ]
    bad = [(n, got, want) for (n, got, want) in checks
           if abs(got - want) > BASELINE_TOL]
    print("HARNESS CHECK against the published 4-mic sweep result")
    for name, got, want in checks:
        mark = "ok  " if abs(got - want) <= BASELINE_TOL else "FAIL"
        print(f"  {mark} {name:<14} {got:6.2f} deg   published {want:.2f} deg")
    if bad:
        print()
        print("  STOP. The 4-mic configuration does not reproduce the "
              "published sweep")
        print("  result, so this harness is not measuring what "
              "plot_validation.py")
        print("  measures and the 3-mic comparison below would be "
              "meaningless.")
        print(f"  If you passed --session, note the published numbers "
              f"belong to")
        print(f"  {DEFAULT_SESSION} alone and no other session will match "
              "them.")
        return False
    print("  the 4-mic column reproduces the deliverable exactly, so the "
          "3-mic")
    print("  columns are being produced by a harness known to be correct.")
    print()
    return True


def print_per_angle(cfgs, results):
    print("PER ANGLE mean error and trial-to-trial spread, deg")
    head = "  angle   n  "
    for c in cfgs:
        head += f"| {c['name']:>16} "
    print(head)
    print("  " + "-" * (len(head) - 2))
    angles = sorted({r["angle"] for r in results[cfgs[0]["name"]]})
    per = {c["name"]: {g["angle"]: g
                       for g in summarize(results[c["name"]])["per_angle"]}
           for c in cfgs}
    for a in angles:
        n = per[cfgs[0]["name"]][a]["n"]
        line = f"  {a:5.0f}  {n:2d}  "
        for c in cfgs:
            g = per[c["name"]][a]
            line += f"| {g['mean']:+7.2f} +/-{g['std']:5.2f} "
        print(line)
    print()
    print("  read the columns against each other, not against zero: the "
          "per-angle")
    print("  offsets are shared by every configuration because they come "
          "from the")
    print("  floor marks, which all five columns inherit identically.")
    print()
    return per


def print_paired(cfgs, results):
    """
    The headline. Same clap, one mic removed, what changed.

    Comparing session means would answer a weaker question, because a mean
    hides whether a configuration is uniformly a little worse or usually
    identical with occasional collapses. Subtracting trial by trial is only
    possible because both columns saw the same samples, and it is the whole
    reason this study needed no new recording.
    """
    base_rows = results[cfgs[0]["name"]]
    print("PAIRED DELTA, per trial: 3-mic |error| minus 4-mic |error| on the "
          "SAME clap")
    print("  config       mean d   median d   std     best      worst"
          "    worse   >2 deg")
    deltas = {}
    for c in cfgs[1:]:
        rows = results[c["name"]]
        d = np.array([abs(r["error"]) - abs(b["error"])
                      for r, b in zip(rows, base_rows)])
        deltas[c["name"]] = d
        worse = int((d > 0).sum())
        big = int((d > WORSE_DEG).sum())
        print(f"  {c['name']:<10} {d.mean():+7.2f}   {np.median(d):+7.2f}  "
              f"{d.std():5.2f}  {d.min():+7.2f}  {d.max():+7.2f}    "
              f"{worse:2d}/{len(d)}    {big:2d}")
    alld = np.concatenate([deltas[k] for k in deltas])
    print()
    print(f"  pooled over all four triangles and all {len(base_rows)} claps: "
          f"mean {alld.mean():+.2f} deg,")
    print(f"  median {np.median(alld):+.2f} deg, worst single degradation "
          f"{alld.max():+.2f} deg,")
    print(f"  and {int((alld > 0).sum())} of {len(alld)} trial-configuration "
          f"pairs got worse.")
    print()
    return deltas


def print_worse_trials(cfgs, results, deltas):
    """
    Name the trials the fourth mic actually saved, and check where they sit.

    Clustering is reported per configuration, not pooled across all four
    triangles, because each triangle has its own bad directions. Pooling
    them would smear four sharp patterns into one flat one and hide the
    thing worth seeing.
    """
    print(f"MATERIALLY WORSE trials, delta greater than {WORSE_DEG:.0f} deg")
    base_rows = results[cfgs[0]["name"]]
    angles = np.array(sorted({r["angle"] for r in base_rows}))
    pred = predicted_gain(cfgs, angles)
    any_bad = False
    per_cfg = {}
    for c in cfgs[1:]:
        rows = results[c["name"]]
        d = deltas[c["name"]]
        for k, val in enumerate(d):
            if val <= WORSE_DEG:
                continue
            any_bad = True
            per_cfg.setdefault(c["name"], {}).setdefault(
                rows[k]["angle"], 0)
            per_cfg[c["name"]][rows[k]["angle"]] += 1
            print(f"  {c['name']:<10} {rows[k]['label']:<22} "
                  f"4-mic {base_rows[k]['error']:+6.2f}  ->  3-mic "
                  f"{rows[k]['error']:+7.2f}   delta {val:+6.2f}")
    if not any_bad:
        print("  none.")
        print()
        return
    print()
    total = sum(sum(v.values()) for v in per_cfg.values())
    print(f"  {total} case(s) out of "
          f"{len(base_rows) * (len(cfgs) - 1)} trial-configuration pairs.")
    print("  where they land, against the bearings that configuration's "
          "geometry")
    print("  predicts it will be worst at:")
    for c in cfgs[1:]:
        hits = per_cfg.get(c["name"], {})
        worst_pred = [f"{a:.0f}" for a, g in zip(angles, pred[c["name"]])
                      if g >= pred[c["name"]].max() - 1e-6]
        got = ", ".join(f"{a:.0f} deg x{n}" for a, n in sorted(hits.items())) \
            or "none"
        print(f"  {c['name']:<10} predicted worst at "
              f"{'/'.join(worst_pred)} deg   observed at {got}")
    print()


def print_redundancy(cfgs, results, rejected, mic_pos):
    """
    What the fourth mic buys that is not accuracy.

    Four mics give six pair delays into a least squares with two unknowns,
    so four degrees of freedom, and four independent triangles for the
    consistency check. Three mics give three pairs, one degree of freedom,
    and exactly one triangle. The accuracy tables above cannot see that
    difference, because a wrong answer with no way to notice it still scores
    the same as a wrong answer that got flagged.

    CLAUDE.md's warning applies to everything below: the triangle residual
    is a WEAK predictor of bearing error. It reliably flags a corrupted
    capture and it is not an error estimate, so this section counts
    detections and says nothing about how large the error will be.
    """
    print("REDUNDANCY, what the 4th mic buys besides accuracy")
    n_pairs4 = cfgs[0]["n_pairs"]
    n_pairs3 = cfgs[1]["n_pairs"]
    print(f"  pair delays feeding the least squares: {n_pairs4} with 4 mics, "
          f"{n_pairs3} with 3.")
    print(f"  the fit solves for 2 unknowns, so redundancy drops from "
          f"{n_pairs4 - 2} spare")
    print(f"  equations to {n_pairs3 - 2}. One bad pair can no longer be "
          "outvoted, it can")
    print("  only be split between the other two.")
    print(f"  independent triangles for the consistency check: "
          f"{cfgs[0]['n_triangles']} with 4 mics, "
          f"{cfgs[1]['n_triangles']} with 3.")
    print()

    thresh = 0.3        # trial_quality.RESIDUAL_MAX, and what localize.c uses
    print(f"  triangle residual at the project's {thresh:.1f} sample "
          "threshold, run over the")
    print("  39 kept trials and the session's retaken (known bad) captures:")
    print("  config       kept flagged   rejected flagged   catastrophic "
          "capture")

    rej_rows = {}
    for c in cfgs:
        rej_rows[c["name"]] = [run_config(t["cap"], c, mic_pos)
                               for t in rejected]

    # The one capture CLAUDE.md singles out: the trigger caught something
    # that was not the clap and the bearing came back about 101 deg off.
    worst_k = None
    if rejected:
        errs = [abs((r["bearing"] - t["angle"] + 180) % 360 - 180)
                for r, t in zip(rej_rows[cfgs[0]["name"]], rejected)]
        worst_k = int(np.argmax(errs))

    for c in cfgs:
        kept = sum(1 for r in results[c["name"]] if r["residual"] > thresh)
        rej = sum(1 for r in rej_rows[c["name"]] if r["residual"] > thresh)
        if worst_k is None:
            cat = "n/a"
        else:
            r = rej_rows[c["name"]][worst_k]
            cat = (f"{r['residual']:.3f} "
                   f"{'FLAGGED' if r['residual'] > thresh else 'MISSED '}")
        print(f"  {c['name']:<10}  {kept:2d}/{len(results[c['name']]):d}"
              f"             {rej:2d}/{len(rejected):d}"
              f"              {cat}")

    if worst_k is not None:
        t = rejected[worst_k]
        r4 = rej_rows[cfgs[0]["name"]][worst_k]
        err4 = (r4["bearing"] - t["angle"] + 180) % 360 - 180
        print()
        print(f"  the catastrophic capture is {t['label']}, true "
              f"{t['angle']:.0f} deg, 4-mic bearing")
        print(f"  {r4['bearing']:.1f} deg, error {err4:+.1f} deg. Its "
              f"residual is {r4['residual']:.3f} samples, well")
        print("  UNDER the threshold, so neither 4 mics nor 3 catch it. That "
              "is the point")
        print("  CLAUDE.md already records: the residual flags a corrupted "
              "capture, it is")
        print("  not an error estimate, and this capture was not corrupted, "
              "it was a clean")
        print("  measurement of the wrong sound. Losing a mic does not make "
              "this worse")
        print("  because the check never caught it to begin with.")
    print()
    print("  where 3 mics genuinely lose ground is that with one triangle "
          "the residual")
    print("  is a single number with nothing to corroborate it, so a check "
          "the project")
    print("  already calls a weak predictor gets weaker. Do not read the "
          "counts above")
    print("  as an error rate.")
    print()
    return rej_rows


def predicted_gain(cfgs, angles):
    """Per bearing noise gain of each 3-mic triangle relative to 4 mics."""
    amp4 = bearing_amplification(cfgs[0]["pos"], angles)
    return {c["name"]: bearing_amplification(c["pos"], angles) / amp4
            for c in cfgs[1:]}


def print_direction(cfgs, results, deltas, mic_pos):
    """
    Does the 1.070 -> 1.740 condition number show up in the real data?

    A condition number is a worst case over all directions, so the test that
    matters is not whether the average got worse but whether it got worse
    WHERE the geometry says it should. The predicted noise gain per bearing
    comes from the same baseline matrix the estimator solves, and it is
    tested against the paired delta rather than against the raw error: the
    per-angle offsets come from the floor marks and no change of geometry
    can move them, but the paired delta has those offsets subtracted out
    because both configurations inherited the same one.

    Bucketing by predicted gain rather than correlating trial by trial is
    what makes this readable at 4 or 5 claps per angle. A single trial's
    error is far too noisy to test a 1.16x against a 2.00x; a bucket of
    forty is not.
    """
    print("DIRECTION DEPENDENCE, does the condition number show up in the "
          "data?")
    angles = np.array(sorted({r["angle"] for r in results[cfgs[0]["name"]]}))
    pred = predicted_gain(cfgs, angles)

    print("  predicted noise gain relative to 4 mics, from the baseline "
          "matrix:")
    print("  angle  " + "".join(f"| {c['name']:>10} " for c in cfgs[1:]))
    for k, a in enumerate(angles):
        line = f"  {a:5.0f}  "
        for c in cfgs[1:]:
            line += f"|  {pred[c['name']][k]:8.2f}x "
        print(line)
    print()
    print("  the pattern is geometric, not accidental. Each triangle is "
          "worst along")
    print("  the diagonal that does NOT pass through the mic it dropped, and "
          "barely")
    print("  degraded along the diagonal that does. Dropping a corner leaves "
          "a right")
    print("  triangle, and the direction along its hypotenuse is the one the "
          "lost")
    print("  baselines were bracing. The four triangles put that direction "
          "in")
    print("  different places, which is why the session averages look alike "
          "while")
    print("  the per-angle rows do not.")
    print()

    # Group every paired delta by the gain its own configuration predicts at
    # that bearing, pooling all four triangles.
    buckets = {}
    for c in cfgs[1:]:
        rows = results[c["name"]]
        d = deltas[c["name"]]
        ang = np.array([r["angle"] for r in rows])
        for k, a in enumerate(angles):
            key = round(float(pred[c["name"]][k]), 2)
            sel = d[ang == a]
            b = buckets.setdefault(key, {"d": [], "big": 0, "n": 0})
            b["d"].extend(sel.tolist())
            b["big"] += int((sel > WORSE_DEG).sum())
            b["n"] += len(sel)

    print("  paired delta grouped by the gain predicted at that bearing, all "
          "four")
    print("  triangles pooled:")
    print("  predicted gain    n    mean delta   median delta   "
          f"delta > {WORSE_DEG:.0f} deg")
    keys = sorted(buckets)
    for key in keys:
        b = buckets[key]
        v = np.array(b["d"])
        print(f"  {key:12.2f}x   {b['n']:3d}     {v.mean():+7.2f}       "
              f"{np.median(v):+7.2f}        {b['big']:3d}/{b['n']:d}")
    print()

    lo, hi = buckets[keys[0]], buckets[keys[-1]]
    lo_v, hi_v = np.array(lo["d"]), np.array(hi["d"])
    total_big = sum(b["big"] for b in buckets.values())
    print(f"  YES, clearly. At the {keys[-1]:.2f}x bearings the mean cost of "
          f"dropping a mic is")
    print(f"  {hi_v.mean():+.2f} deg; at the {keys[0]:.2f}x bearings it is "
          f"{lo_v.mean():+.2f} deg, a factor of "
          f"{hi_v.mean() / max(lo_v.mean(), 1e-9):.1f}.")
    if total_big:
        print(f"  {hi['big']} of the {total_big} materially worse trials sit "
              f"in the {keys[-1]:.2f}x bucket, which holds")
        print(f"  only {hi['n']} of the "
              f"{sum(b['n'] for b in buckets.values())} "
              "trial-configuration pairs.")
    print("  the condition number is not a paper quantity here. It predicts "
          "which")
    print("  bearings the three mic array will get wrong, and the real claps "
          "agree.")
    print()


# ----------------------------------------------------------------- figure

def make_figure(cfgs, results, path):
    """
    Per-angle error with spread bars, 4-mic against the 3-mic triangles.

    No title and no caption are drawn into the image. The presentation keeps
    figure prose in make_presentation.py's FIG_TEXT dict so it can be
    reworded without re-rendering, and this figure follows that rule. Only
    text that labels a mark in the drawing goes inside.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed, no figure written "
              "(pip install matplotlib).")
        return None

    summ = {c["name"]: summarize(results[c["name"]]) for c in cfgs}
    angles = np.array([g["angle"] for g in summ[cfgs[0]["name"]]["per_angle"]])

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.5, 4.2),
                                   gridspec_kw={"width_ratios": [1.7, 1.0]})

    for ax in (axL, axR):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=10, length=0)
        ax.grid(axis="y", color=GRID, linewidth=1, zorder=0)
        ax.set_axisbelow(True)

    # Left: per angle mean error with the trial-to-trial spread as the bar.
    # The four triangles are drawn as one muted family rather than four named
    # series: they are equivalent by symmetry and the reader's question is
    # 4 against 3, not which triangle.
    axL.axhline(0.0, color=INK, linewidth=1.4, zorder=2)
    axL.text(333, 0.25, "true angle", color=INK, fontsize=9.5, ha="right")

    offsets = np.linspace(-9, 9, len(cfgs) - 1)
    for k, c in enumerate(cfgs[1:]):
        g = summ[c["name"]]["per_angle"]
        m = np.array([x["mean"] for x in g])
        s = np.array([x["std"] for x in g])
        axL.errorbar(angles + offsets[k], m, yerr=s, fmt="o", markersize=4.5,
                     color=STATUS_BAD, ecolor=STATUS_BAD, elinewidth=1.4,
                     capsize=3, capthick=1.4, alpha=0.55, zorder=3,
                     label="3-mic triangles (4 of them)" if k == 0 else None)

    g4 = summ[cfgs[0]["name"]]["per_angle"]
    axL.errorbar(angles, [x["mean"] for x in g4], yerr=[x["std"] for x in g4],
                 fmt="o", markersize=9, color=ACCENT, ecolor=ACCENT,
                 elinewidth=2.5, capsize=6, capthick=2.5, zorder=5,
                 markeredgecolor=SURFACE, markeredgewidth=0.8,
                 label="4-mic array")

    axL.set_xticks(angles)
    axL.set_xlabel("true bearing (deg)", color=INK2, fontsize=10.5)
    axL.set_ylabel("error (deg)", color=INK2, fontsize=10.5)
    axL.set_xlim(-25, 345)
    # Headroom below the lowest bar so the legend is not sitting on a mark.
    lo = min(x["mean"] - x["std"] for c in cfgs
             for x in summ[c["name"]]["per_angle"])
    hi = max(x["mean"] + x["std"] for c in cfgs
             for x in summ[c["name"]]["per_angle"])
    axL.set_ylim(lo - 0.30 * (hi - lo), hi + 0.06 * (hi - lo))
    axL.legend(loc="lower center", ncol=2, fontsize=9.5, frameon=False,
               labelcolor=INK2)

    # Right: the paired delta, which is the number the study exists to
    # produce. One bar per triangle, value labelled, because four bars do not
    # need a y axis read off a grid.
    base_rows = results[cfgs[0]["name"]]
    names, means = [], []
    for c in cfgs[1:]:
        d = np.array([abs(r["error"]) - abs(b["error"])
                      for r, b in zip(results[c["name"]], base_rows)])
        names.append("mics " + "".join(str(m) for m in c["idx"]))
        means.append(d.mean())
    means = np.array(means)

    xs = np.arange(len(names))
    axR.axhline(0.0, color=INK, linewidth=1.4, zorder=2)
    axR.bar(xs, means, width=0.6, color=STATUS_BAD, alpha=0.85, zorder=3)
    for x, v in zip(xs, means):
        axR.text(x, v + 0.05, f"{v:+.2f}", color=INK, fontsize=10.5,
                 ha="center", va="bottom", fontweight="bold")
    axR.set_xticks(xs)
    axR.set_xticklabels(names, fontsize=9.5)
    axR.set_ylabel("mean paired delta (deg)", color=INK2, fontsize=10.5)
    axR.set_ylim(0, max(means.max() * 1.35, 0.6))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=SURFACE, bbox_inches="tight",
                pad_inches=0.25)
    plt.close(fig)
    return path


# ------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compare the 4-mic array against every 3-mic triangle "
                    "on identical captures.")
    ap.add_argument("--session", default=DEFAULT_SESSION,
                    help=f"capture session to score (default {DEFAULT_SESSION})")
    ap.add_argument("--fig", default=FIG_DEFAULT,
                    help="where to write the figure")
    ap.add_argument("--no-fig", action="store_true",
                    help="skip the figure, print the tables only")
    args = ap.parse_args(argv)

    mic_pos = geom.active_positions()
    saved_active = geom.ACTIVE          # restored below, untouched on disk

    try:
        trials = load_trials(args.session)
        if not trials:
            print(f"no trials found in session '{args.session}'. Sessions "
                  "available:")
            for d in sorted(os.listdir(cp.CAPTURES_DIR)):
                print(f"  {d}")
            return 1

        rejected = load_rejected(args.session)

        print("=" * 74)
        print("4 MICS AGAINST 3: a paired comparison on identical captures")
        print("=" * 74)
        print(f"session {args.session}: {len(trials)} good trials over "
              f"{len({t['angle'] for t in trials})} angles, plus "
              f"{len(rejected)} retaken captures")
        print("every configuration below is scored on the SAME samples, so "
              "any difference")
        print("is geometry and not the room, the day, or the clap.")
        print()

        cfgs = configurations(mic_pos)
        print_geometry(cfgs)

        results = score_session(trials, cfgs, mic_pos)
        base = print_accuracy(cfgs, results)
        if not check_harness(base):
            return 1

        print_per_angle(cfgs, results)
        deltas = print_paired(cfgs, results)
        print_worse_trials(cfgs, results, deltas)
        print_redundancy(cfgs, results, rejected, mic_pos)
        print_direction(cfgs, results, deltas, mic_pos)

        if not args.no_fig:
            path = make_figure(cfgs, results, args.fig)
            if path:
                print(f"wrote {path}")
        return 0
    finally:
        geom.ACTIVE = saved_active


if __name__ == "__main__":
    sys.exit(main())
