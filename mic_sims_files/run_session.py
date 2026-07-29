"""
run_session.py

One command for a whole bench session: it tells you where to put the source,
records the trials for that angle, judges each one on the spot, and moves on.

The problem it solves. A sweep is 8 angles times 5 trials, which used to be
40 hand-typed runs of catch_audio4.py, each with its own --tag, plus keeping
track in your head of which angles were already done, plus finding out hours
later at analysis time that trial 3 of angle 225 was a bad clap. This walks
the sweep for you, so the only things you do at the bench are move the
source, press the button and clap.

Typical use:

    python run_session.py COM4 --session 2026-07-29-sweep \
        --angles 0,45,90,135,180,225,270,315 --trials 5

Run the same command again after a break and it resumes: angles that already
have their five good trials are skipped, and an angle that is part way
through carries on at the next trial number. Nothing is overwritten, because
trial numbering comes from capture_paths.next_trial_number, which exists for
exactly this.

What happens to a bad trial. After every capture the quality check in
trial_quality.py runs and prints a verdict before you move. If it fails you
are offered a retake, and taking it RENAMES the bad capture from
trial<K>.npy to rejected<N>.npy in the same folder. That means:
  - the samples are still on disk, because a bad capture is still evidence
  - nothing in the analysis sees it, because every script globs trial*.npy
  - the retake becomes trial<K>, so the good trials stay numbered 1..5
  - the reason is written to the session's quality_log.txt
You can also keep a failing trial deliberately. It stays as trial<K> and is
logged as KEPT-FAIL, so the decision is on the record rather than implied by
its absence.

No board on the desk? Replay real captures through the whole path instead:

    python run_session.py --replay 2026-07-27-wall-2m --session testrun \
        --angles 0,45 --trials 2 --no-finish

Other useful forms:

    python run_session.py --summary --session 2026-07-29-sweep
        just the progress table, touches no hardware

    python catch_audio4.py COM4 --tag angle090
        still there, unchanged, for a single trial by hand
"""

import argparse
import datetime
import os
import sys

import numpy as np

import array_geometry as geom
import capture_paths as cp
import compare_board as cb
import trial_quality as tq
import wav4_stream as ws


def tag_for(angle):
    """Folder name for an angle. angle045, the form capture_paths expects."""
    return f"angle{int(round(angle)) % 360:03d}"


def ask(prompt, default=""):
    """
    One prompt, lowercased, with Enter meaning the default.

    End of input means quit rather than default, because reaching the end of
    stdin means nobody is at the keyboard. That is what makes a scripted
    replay run terminate instead of retaking the same trial forever.
    """
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        print("\n(no more input, ending the session here)")
        return "q"
    if not sys.stdin.isatty():
        print()          # a piped answer does not echo, so close the line
    return answer or default


# --------------------------------------------------------------- progress

def progress(session, tags):
    """
    How far each angle has got: good trials on disk and rejects beside them.

    Reads the folders rather than any state file, so it is correct after a
    crash, after deleting a trial by hand, and for a session recorded before
    this script existed.
    """
    counts = {t: {"good": 0, "rejected": 0} for t in tags}
    for d in cp.find_captures(session):
        if d["tag"] in counts:
            counts[d["tag"]]["good"] += 1
    for t in tags:
        counts[t]["rejected"] = cp.next_reject_number(session, t) - 1
    return counts


def print_progress(session, tags, angles, target):
    """The table of what is done, printed at the start and at the end."""
    counts = progress(session, tags)
    print(f"session {session}   target {target} trial(s) at each of "
          f"{len(tags)} angle(s)")
    print("  angle   good   rejected   status")
    total = 0
    for ang, t in zip(angles, tags):
        c = counts[t]
        total += c["good"]
        left = target - c["good"]
        status = "done" if left <= 0 else f"{left} to go"
        print(f"  {ang:5.0f}   {c['good']:4d}   {c['rejected']:8d}   {status}")
    print(f"  {total} of {target * len(tags)} good trials recorded")
    return counts


# ------------------------------------------------------------ one capture

def board_line(report_path):
    """
    One line summarising what the board itself said about the trial just
    taken. report_path is the saved trial<K>_bearing.txt, or None if the
    board sent nothing.

    Parsed with compare_board.parse_report so there is still only one piece
    of code that knows the report format. Worth showing at the bench because
    a blank bearing here is the visible symptom of running firmware older
    than f5c3d78, and you want to know that on trial 1, not after 40 of them.
    """
    if not report_path:
        return "no report from the board (older firmware, or Localize_Init " \
               "failed at boot)"
    parsed = cb.parse_report(report_path)

    if parsed["failed"]:
        return f"board reported FAILED: {parsed['failed']}"
    if parsed["bearing"] is None:
        return ("board printed blank floats, so it is running firmware "
                "older than f5c3d78. Rebuild and flash.")
    extra = ""
    if parsed["residual"] is not None:
        extra = f", residual {parsed['residual']:.3f} samples"
    if parsed["inconsistent"]:
        extra += "  (board flagged it inconsistent)"
    return f"board says bearing {parsed['bearing']:.2f} deg{extra}"


def record_trial(port, session, tag, k, angle):
    """
    Take one trial: wait for the dump, save it, judge it.

    Returns (Quality, saved) or (None, False) if nothing arrived. Saving
    happens before judging on purpose. A capture the check rejects is still
    written to disk first, so a failure can never lose data, and the reject
    path below is a rename rather than a decision about whether to write.
    """
    cp.ensure_dirs(session, tag)
    print(f"\n--- {tag}  trial {k}  ---")
    port.reset_input_buffer()      # drop boot text and anything stale
    print("Press the blue button on the board, then clap.")

    cap = ws.read_capture(port, log=lambda s: print(f"  {s}"))
    if cap is None:
        return None, False

    np.save(cp.trial_npy(session, tag, k), cap)
    ws.save_wavs(cap, lambda m: cp.trial_wav(session, tag, k, m))
    print(f"  saved {cp.describe(cp.trial_npy(session, tag, k))} "
          f"(peak {int(np.max(np.abs(cap)))} of 32767)")

    report = ws.read_report(port)
    report_path = None
    if report:
        report_path = cp.trial_report(session, tag, k)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
    print(f"  {board_line(report_path)}")

    quality = tq.assess(cap, angle)
    for line in quality.lines("  "):
        print(line)
    return quality, True


def reject_trial(session, tag, k):
    """
    Move a judged-bad trial out of the way of the analysis.

    Rename, do not delete. The samples stay readable next to the good ones
    and the trial numbering closes up behind them, so the retake takes the
    number the bad capture was going to have.
    """
    n = cp.next_reject_number(session, tag)
    moves = [(cp.trial_npy(session, tag, k), cp.rejected_npy(session, tag, n)),
             (cp.trial_report(session, tag, k),
              cp.rejected_report(session, tag, n))]
    moves += [(cp.trial_wav(session, tag, k, m),
               cp.rejected_wav(session, tag, n, m)) for m in range(4)]
    for src, dst in moves:
        if os.path.exists(src):
            os.replace(src, dst)
    return n, os.path.basename(cp.rejected_npy(session, tag, n))


def log_trial(session, tag, name, verdict, quality):
    """One line per trial in the session quality log, kept or not."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if quality is None:
        detail = "no data received"
    elif quality.ok:
        detail = (f"bearing {quality.bearing:.2f} deg, "
                  f"error {quality.error:+.2f} deg, "
                  f"residual {quality.residual:.3f}")
    else:
        detail = quality.reason()
    cp.append_quality_log(
        session, f"{stamp}  {tag}  {name:<14}{verdict:<10} {detail}")


# -------------------------------------------------------------- one angle

def run_angle(port, session, tag, angle, target, counts):
    """
    Record this angle until it has target good trials.

    Returns "next" to carry on with the sweep or "quit" to stop the session.
    """
    have = counts[tag]["good"]
    print()
    print("=" * 72)
    print(f"ANGLE {angle:.0f} deg   folder {tag}   {have} of {target} "
          f"good trials so far")
    print("=" * 72)
    if have >= target:
        print("Already complete, skipping. Delete a trial and rerun if you "
              "want to redo it.")
        return "next"

    # 1.5 m, not 1 m. The plane-wave model needs roughly 2*D^2/lambda of
    # distance, which for this 13.55 cm aperture is 0.86 m at 8 kHz, and a
    # clap has real energy up that high. Distance also cuts the angular error
    # from imprecise hand placement: 5 cm of it is 7 deg at 40 cm but under
    # 2 deg at 1.5 m.
    print(f"Put the source at {angle:.0f} degrees, 1.5 m or more out, at "
          f"array height.")
    print("0 deg is off the mic1/mic3 edge, 90 deg is off the mic0/mic1 "
          "edge, counterclockwise.")
    answer = ask("Press Enter when it is in place  "
                 "(s = skip this angle, q = end session): ")
    if answer.startswith("s"):
        print("Skipped.")
        return "next"
    if answer.startswith("q"):
        return "quit"

    while have < target:
        k = cp.next_trial_number(session, tag)
        quality, saved = record_trial(port, session, tag, k, angle)

        if not saved:
            log_trial(session, tag, f"trial{k}", "NODATA", None)
            print("  Nothing arrived. The board only dumps after the button "
                  "press, and\n  the green LED stays on until a clap passes "
                  "the trigger level.")
            answer = ask("  [Enter] try again, s = skip this angle, "
                         "q = end session: ")
            if answer.startswith("s"):
                return "next"
            if answer.startswith("q"):
                return "quit"
            continue

        if quality.ok:
            have += 1
            counts[tag]["good"] = have
            log_trial(session, tag, f"trial{k}", "PASS", quality)
            print(f"  kept as trial{k}. {have} of {target} good at this "
                  f"angle.")
            continue

        answer = ask("  [Enter] retake this trial, k = keep it anyway, "
                     "s = skip this angle, q = end session: ")
        if answer.startswith("k"):
            have += 1
            counts[tag]["good"] = have
            log_trial(session, tag, f"trial{k}", "KEPT-FAIL", quality)
            print(f"  KEPT as trial{k} despite failing. It will appear in the "
                  f"plot.\n  Logged in {cp.describe(cp.quality_log_path(session))} "
                  f"as KEPT-FAIL.")
            continue

        n, name = reject_trial(session, tag, k)
        counts[tag]["rejected"] = n
        log_trial(session, tag, name, "REJECT", quality)
        print(f"  REJECTED: trial{k} renamed to {name}, which no analysis "
              f"script reads.\n  The samples are still there and the reason "
              f"is in "
              f"{cp.describe(cp.quality_log_path(session))}.")

        if answer.startswith("s"):
            return "next"
        if answer.startswith("q"):
            return "quit"
        print(f"  Retaking as trial{k}.")

    return "next"


# ----------------------------------------------------------- end of session

def finish(session):
    """
    The two things worth running once the sweep is in: the validation plot
    and the board-versus-Python acceptance test.

    Done here rather than left as advice at the end, because the whole point
    of the session runner is that the next step never has to be remembered.
    Both are imported and called rather than shelled out, so they run against
    the same geometry this session was recorded with.
    """
    print("\n" + "=" * 72)
    print("END OF SESSION: running the analysis")
    print("=" * 72)

    print("\n--- plot_validation.py (estimated vs true bearing) ---")
    try:
        import plot_validation as pv
        pv.main([], session)
        png = os.path.abspath("validation_plot.png")
        if os.path.exists(png):
            print(f"plot written to {png}")
    except Exception as exc:                       # noqa: BLE001
        print(f"plot_validation failed: {exc}")

    print("\n--- compare_board.py (firmware vs Python reference) ---")
    try:
        cb.main(["--session", session])
    except Exception as exc:                       # noqa: BLE001
        print(f"compare_board failed: {exc}")

    print(f"\ncaptures:     {cp.session_dir(session)}")
    print(f"room notes:   {cp.notes_path(session)}")
    print(f"quality log:  {cp.quality_log_path(session)}")


# ------------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(
        description="Guided 4-mic capture session: one command for a whole "
                    "angle sweep, with a quality check after every trial.")
    p.add_argument("port", nargs="?", default="COM4",
                   help="serial port the board is on (default COM4)")
    p.add_argument("--session", default=None,
                   help="folder under captures/ for this sitting. Defaults to "
                        "today's date. Rerunning the same session resumes it.")
    p.add_argument("--angles", default="0,45,90,135,180,225,270,315",
                   help="comma separated true angles in degrees, in the order "
                        "you want to walk them")
    p.add_argument("--trials", type=int, default=5,
                   help="how many GOOD trials to collect per angle "
                        "(default 5). Rejected retakes do not count.")
    p.add_argument("--notes", default=None,
                   help="free text for the session notes.txt. Record distance "
                        "to the nearest wall and how far away you clap: those "
                        "set when the first echo arrives.")
    p.add_argument("--summary", action="store_true",
                   help="print the progress table and exit. No serial port is "
                        "opened, so this is safe to run any time.")
    p.add_argument("--no-finish", action="store_true",
                   help="skip the plot and the board comparison at the end")
    p.add_argument("--replay", default=None,
                   help="no board: replay captures instead. Takes a session "
                        "name, a folder or an .npy path, comma separated. "
                        "Captures cycle if the sweep asks for more than exist.")
    p.add_argument("--inject", default=None,
                   help="with --replay, break the replayed trials on purpose "
                        "to exercise the retake path. Comma separated list "
                        "applied to consecutive trials, e.g. "
                        "none,clip,dead,weak.")
    return p


def main(argv):
    args = build_parser().parse_args(argv)

    angles = [float(a) for a in args.angles.split(",") if a.strip()]
    if not angles:
        raise SystemExit("--angles is empty")
    if args.trials < 1:
        raise SystemExit("--trials must be at least 1")
    tags = [tag_for(a) for a in angles]
    session = args.session or datetime.date.today().isoformat()

    d = geom.describe(geom.active_positions())
    print(f"array geometry: {geom.ACTIVE} "
          f"({'measured' if geom.is_measured() else 'NOMINAL, not calipered'})"
          f", condition number {d['cond']:.2f}")
    if d["rank"] < 2:
        raise SystemExit("the active layout is collinear, so no bearing from "
                         "this session could mean anything. Fix "
                         "array_geometry.py first.")
    counts = print_progress(session, tags, angles, args.trials)

    if args.summary:
        return 0

    if args.replay:
        import replay_source as rs
        need = sum(max(0, args.trials - counts[t]["good"]) for t in tags)
        injects = ([f.strip() for f in args.inject.split(",")]
                   if args.inject else None)
        # A couple of spare frames so a retake has something left to read.
        port = rs.fake_port(args.replay.split(","), need + 4, injects)
        source = f"REPLAY of {args.replay}"
        print(f"\nREPLAY MODE: no board involved. Frames come from "
              f"{args.replay}.")
        print("Every other part of the path is the real one: magic sync, "
              "length field,\nfour channel blocks, report, save, quality "
              "check, retake.")
    else:
        try:
            port = ws.open_port(args.port)
        except Exception as exc:                   # noqa: BLE001
            print(f"\ncould not open {args.port}: {exc}")
            print("Plug the board in, close any other terminal holding the "
                  "port, or use\n--replay to run without hardware.")
            return 1
        source = f"port {args.port}"
        print(f"\nport {args.port} open at {ws.BAUD} baud.")

    cp.append_session_note(
        session,
        f"{source}, {ws.SAMPLE_RATE} Hz, {ws.NUM_MICS} mics, "
        f"geometry {geom.ACTIVE}, angles {args.angles}, "
        f"{args.trials} trial(s) each",
        args.notes)

    try:
        for angle, tag in zip(angles, tags):
            if run_angle(port, session, tag, angle, args.trials,
                         counts) == "quit":
                print("\nEnding the session here. Rerun the same command to "
                      "pick up where it stopped.")
                break
    except KeyboardInterrupt:
        print("\n\nInterrupted. Nothing is lost: rerun the same command and "
              "it resumes.")
    finally:
        port.close()

    print()
    counts = print_progress(session, tags, angles, args.trials)
    missing = [a for a, t in zip(angles, tags)
               if counts[t]["good"] < args.trials]
    if missing:
        print(f"  still short at: {', '.join(f'{a:.0f}' for a in missing)} "
              f"deg. Rerun the same command to continue.")

    if not args.no_finish:
        finish(session)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
