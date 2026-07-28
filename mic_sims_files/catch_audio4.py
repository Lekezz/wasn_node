import argparse
import datetime
import os

import numpy as np

import capture_paths as cp
import wav4_stream as ws

# 4-channel capture, one trial at a time. The wire format lives in
# wav4_stream.py, which run_session.py uses as well, so there is only one
# piece of code that knows what the board's bytes mean.
#
# For a whole sweep, use run_session.py instead: it walks the angles, prompts
# you between them, and checks each trial before you move on. This script is
# the by-hand version and its command line has not changed.

parser = argparse.ArgumentParser(
    description="Capture 4-channel recordings from the board over serial. "
                "For a whole angle sweep use run_session.py instead.")
parser.add_argument("port", nargs="?", default="COM4",
                    help="serial port (default COM4), e.g. COM7")
parser.add_argument("--tag", default=None,
                    help="which angle this is, e.g. --tag angle090. Becomes a "
                         "folder inside the session, holding one .npy per "
                         "trial plus a wav/ subfolder of listening copies. "
                         "Without --tag you get the legacy loose capture.npy "
                         "in mic_sims_files, overwritten each run.")
parser.add_argument("--trials", type=int, default=1,
                    help="how many recordings to take in a row at this angle "
                         "(default 1). Each one waits for its own button "
                         "press. Trial numbers continue past any files "
                         "already saved for this angle, so you can also just "
                         "rerun the command to add more.")
parser.add_argument("--session", default=None,
                    help="folder under captures/ grouping everything recorded "
                         "in one sitting under one room setup, e.g. "
                         "--session 2026-07-24-wall-2m. Defaults to today's "
                         "date. Start a new session whenever you move the "
                         "array, because the room sets the echo timing.")
parser.add_argument("--notes", default=None,
                    help="free text saved to the session's notes.txt. Record "
                         "distance to the nearest wall and how far away you "
                         "clap: those set when the first echo arrives, which "
                         "is what decides whether a trial is trustworthy.")
args = parser.parse_args()

if args.trials < 1:
    parser.error("--trials must be at least 1")
if args.trials > 1 and not args.tag:
    parser.error("--trials needs --tag so the recordings get distinct names")

SESSION = args.session or datetime.date.today().isoformat()

PORT = args.port
SAMPLE_RATE = ws.SAMPLE_RATE
NUM_MICS = ws.NUM_MICS

# Recorded into notes.txt so a session says which array layout produced it.
# Imported lazily-ish here (not at top) only to keep the import list tidy.
import array_geometry as _geom      # noqa: E402
GEOMETRY = _geom.ACTIVE

ser = ws.open_port(PORT)


def write_session_notes():
    """
    Record what the room looked like for this session. Written once when the
    session folder is created, and appended to if you pass --notes again on a
    later run, so the history of a sitting stays in one place. The formatting
    lives in capture_paths because run_session.py writes the same file.
    """
    return cp.append_session_note(
        SESSION,
        f"port {PORT}, {SAMPLE_RATE} Hz, {NUM_MICS} mics, "
        f"geometry {GEOMETRY}",
        args.notes)


def paths_for(tag, k):
    """
    Where trial k of this angle goes: the data file, a function giving the
    per-mic listening copy, and the on-board report. tag None means the legacy
    loose form.
    """
    if tag is None:
        return (os.path.join(cp.BASE_DIR, "capture.npy"),
                lambda m: os.path.join(cp.BASE_DIR, f"mic{m}.wav"),
                os.path.join(cp.BASE_DIR, "capture_bearing.txt"))
    cp.ensure_dirs(SESSION, tag)
    return (cp.trial_npy(SESSION, tag, k),
            lambda m: cp.trial_wav(SESSION, tag, k, m),
            cp.trial_report(SESSION, tag, k))


def capture_once(tag, k):
    """
    Wait for one button press, read the four channels, save them.
    Returns the (NUM_MICS, nsamples) array, or None on any read failure.
    """
    npy_name, wav_for, report_name = paths_for(tag, k)
    ser.reset_input_buffer()     # drop boot text / stale bytes; idle = nothing
    print("Ready. Press the blue button on the board now...")

    cap = ws.read_capture(ser)
    if cap is None:
        return None

    ws.save_wavs(cap, wav_for)
    np.save(npy_name, cap)

    # Quick quality hint so a dud trial gets caught now, not at plot time.
    peak = int(np.max(np.abs(cap)))
    if peak >= 32700:
        note = "  WARNING: clipped, clap softer or further"
    elif peak < 2000:
        note = "  WARNING: very quiet, clap harder or closer"
    else:
        note = ""
    print(f"Saved {cp.describe(npy_name)} (peak {peak} of 32767){note}")

    # The board localizes the capture it just sent and prints the result. Show
    # it and keep it beside the samples, so a trial carries the firmware's own
    # answer and can be compared against localize_capture.py later.
    report = ws.read_report(ser)
    if report:
        print("  --- board's own bearing ---")
        for line in report:
            print(f"  | {line}")
        with open(report_name, "w", encoding="utf-8") as f:
            f.write("\n".join(report) + "\n")
        print(f"  saved {cp.describe(report_name)}")
    else:
        print("  (no bearing report from the board: older firmware, or "
              "Localize_Init failed at boot)")

    return cap


if args.tag:
    cp.ensure_dirs(SESSION, args.tag)
    notes_path = write_session_notes()
    start = cp.next_trial_number(SESSION, args.tag)
    print(f"session {SESSION}, angle folder "
          f"{cp.describe(cp.angle_dir(SESSION, args.tag))}")
    if args.notes:
        print(f"notes -> {cp.describe(notes_path)}")

    saved = 0
    for i in range(args.trials):
        k = start + i
        print(f"\n=== {args.tag}  trial {k}  ({i + 1} of {args.trials}) ===")
        if capture_once(args.tag, k) is None:
            print("Stopping this angle. Rerun to continue from where it left "
                  "off.")
            break
        saved += 1
    print(f"\nDone. Saved {saved} trial(s) for {args.tag} in session "
          f"{SESSION}.")
    if saved:
        angle_text = args.tag.replace("angle", "").lstrip("0") or "0"
        print(f"Check this angle now:   python trial_quality.py --true-angle "
              f"{angle_text}")
        print("                        python check_sync.py")
        print("                        python localize_capture.py --true-angle "
              f"{angle_text}")
        print("When the sweep is done: python plot_validation.py")
        print("For a whole sweep with the checks built in: python "
              "run_session.py")
else:
    # Legacy single capture: loose mic0.wav.. and capture.npy, overwritten.
    if capture_once(None, 1) is None:
        ser.close()
        raise SystemExit(1)

ser.close()
