"""
reject_trial.py

Retire a trial after the session has ended.

run_session.py offers a retake at the bench, but some judgements only become
obvious later: you remember the array was set up wrong, or a bearing turns out
to be 100 degrees off because the trigger caught a door rather than the clap.
This does the same thing the runner's retake does, to a capture already on disk.

It follows the project's existing rule exactly: a rejected trial is RENAMED to
rejected<N>.npy, never deleted. Every analysis script globs trial*.npy, so the
capture stops reaching plot_validation.py and compare_board.py while its
samples stay next to the good ones as evidence about the room. The board's own
report and the four listening wavs move with it.

Rejecting leaves a GAP in the trial numbers (1, 2, 4, 5 after rejecting 3).
That is deliberate. Renumbering would break the link between a trial and the
quality_log line and bearing report that already name it, and nothing cares
about density: the analysis globs, and next_trial_number takes the highest plus
one, so a later session still appends cleanly.

Run:
    python reject_trial.py --session NAME --angle 225 --trial 3 --reason "..."
    python reject_trial.py --session NAME --over 10
    python reject_trial.py --session NAME --over 10 --dry-run

--over DEG rejects every trial whose bearing error exceeds DEG degrees, which
is the usual way this gets used: one rule applied to a whole session. It always
lists what it will do and asks before touching anything, unless you pass --yes.
"""

import argparse
import glob
import os
import re
import sys

import numpy as np

import capture_paths as cp
import compare_board as cb
import localize_capture as lc

NUM_MICS = 4


def trial_error(path, true_angle):
    """Bearing error in degrees for one capture, and its triangle residual."""
    cap = np.load(path).astype(float)
    onset, _, _ = lc.find_clap(cap)
    bearing, delays = lc.localize(cap, onset, verbose=False)
    err = ((bearing - true_angle + 180) % 360) - 180
    return err, cb.triangle_residual(delays), bearing % 360


def find_trials(session, angle=None, trial=None):
    """Every (tag, k, path, true_angle) in a session, optionally filtered."""
    out = []
    pattern = os.path.join(cp.session_dir(session), "angle*", "trial*.npy")
    for path in sorted(glob.glob(pattern)):
        tag = os.path.basename(os.path.dirname(path))
        m = re.search(r"angle(\d+)", tag)
        k = re.search(r"trial(\d+)\.npy$", os.path.basename(path))
        if not m or not k:
            continue
        true_angle, k = float(m.group(1)), int(k.group(1))
        if angle is not None and abs(true_angle - angle) > 1e-6:
            continue
        if trial is not None and k != trial:
            continue
        out.append((tag, k, path, true_angle))
    return out


def reject(session, tag, k, reason):
    """
    Rename one trial and everything that belongs to it.

    Returns the reject number used. Renames the .npy first: if anything later
    fails, the capture is already out of the analysis rather than half in it.
    """
    n = cp.next_reject_number(session, tag)

    src = cp.trial_npy(session, tag, k)
    dst = cp.rejected_npy(session, tag, n)
    if not os.path.exists(src):
        raise SystemExit(f"no such trial: {cp.describe(src)}")
    if os.path.exists(dst):
        raise SystemExit(f"reject slot already taken: {cp.describe(dst)}")
    os.rename(src, dst)
    moved = [(src, dst)]

    report_src = cp.trial_report(session, tag, k)
    if os.path.exists(report_src):
        report_dst = cp.rejected_report(session, tag, n)
        os.rename(report_src, report_dst)
        moved.append((report_src, report_dst))

    for mic in range(NUM_MICS):
        wav_src = cp.trial_wav(session, tag, k, mic)
        if os.path.exists(wav_src):
            wav_dst = cp.rejected_wav(session, tag, n, mic)
            os.rename(wav_src, wav_dst)
            moved.append((wav_src, wav_dst))

    cp.append_quality_log(
        session,
        f"{'(after the fact)':<17} {tag:<9} trial{k:<7} REJECTED "
        f"-> rejected{n}.npy  {reason}")
    return n, moved


def main(argv):
    ap = argparse.ArgumentParser(
        description="Retire a trial after the session, using the project's "
                    "rename-not-delete rule.")
    ap.add_argument("--session", required=True,
                    help="session folder under captures/")
    ap.add_argument("--angle", type=float,
                    help="limit to one angle, e.g. --angle 225")
    ap.add_argument("--trial", type=int,
                    help="one trial number, needs --angle")
    ap.add_argument("--over", type=float,
                    help="reject every trial whose bearing error exceeds this "
                         "many degrees")
    ap.add_argument("--reason", default=None,
                    help="why, recorded in the session quality log")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would happen and change nothing")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    args = ap.parse_args(argv)

    if args.trial is not None and args.angle is None:
        raise SystemExit("--trial needs --angle as well")
    if args.over is None and args.trial is None:
        raise SystemExit("say what to reject: --trial K (with --angle) or "
                         "--over DEG")
    if not os.path.isdir(cp.session_dir(args.session)):
        raise SystemExit(f"no such session: {args.session}")

    candidates = find_trials(args.session, args.angle, args.trial)
    if not candidates:
        raise SystemExit("no trials matched")

    print(f"session {args.session}")
    doomed = []
    for tag, k, path, true_angle in candidates:
        err, resid, bearing = trial_error(path, true_angle)
        hit = args.over is None or abs(err) > args.over
        mark = "REJECT" if hit else ""
        print(f"  {tag:<9} trial{k}  true {true_angle:5.0f}  "
              f"bearing {bearing:7.2f}  error {err:+7.2f}  "
              f"residual {resid:.3f}   {mark}")
        if hit:
            reason = args.reason or (
                f"bearing error {err:+.2f} deg exceeds the {args.over:g} deg "
                f"limit for this session" if args.over is not None
                else "rejected after the session")
            doomed.append((tag, k, reason))

    if not doomed:
        print("\nnothing to reject.")
        return 0

    print(f"\n{len(doomed)} trial(s) would be renamed to rejected<N>.npy, "
          f"which no analysis script reads.")
    print("Nothing is deleted. The samples stay in the angle folder.")

    if args.dry_run:
        print("\n--dry-run, so nothing was changed.")
        return 0

    if not args.yes:
        try:
            reply = input("Go ahead? [y/N]: ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes"):
            print("nothing changed.")
            return 1

    print()
    for tag, k, reason in doomed:
        n, moved = reject(args.session, tag, k, reason)
        print(f"  {tag} trial{k} -> rejected{n}.npy  ({len(moved)} files)")
    print(f"\nLogged in {cp.describe(cp.quality_log_path(args.session))}")
    print("Rerun plot_validation.py and compare_board.py to see the effect.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
