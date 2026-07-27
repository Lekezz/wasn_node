import argparse
import datetime
import os
import time
import serial
import wave
import numpy as np

import capture_paths as cp

# 4-channel capture. The firmware dumps, in order:
#   8-byte header: b"WAV4" + 4-byte little-endian per-channel byte count
#   then the four channels back to back (mic0, mic1, mic2, mic3),
#   each one that many bytes of raw int16 samples.
# We sync on the "WAV4" magic instead of reading a fixed count, so any
# boot text or partial buffer left in the stream is skipped cleanly.

parser = argparse.ArgumentParser(
    description="Capture 4-channel recordings from the board over serial.")
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
BAUD = 115200
SAMPLE_RATE = 16000
NUM_MICS = 4
MAGIC = b"WAV4"

# Recorded into notes.txt so a session says which array layout produced it.
# Imported lazily-ish here (not at top) only to keep the import list tidy.
import array_geometry as _geom      # noqa: E402
GEOMETRY = _geom.ACTIVE

# read timeout has to cover four channels at 115200 baud. One second of
# audio is 32000 bytes/channel, 128000 bytes total, about 11 s to send.
# 90 s leaves plenty of room for you to press the button after starting.
ser = serial.Serial(PORT, BAUD, timeout=90)


def read_exact(port, n):
    """Read exactly n bytes or return whatever arrived before timeout."""
    buf = bytearray()
    while len(buf) < n:
        chunk = port.read(n - len(buf))
        if not chunk:            # timeout, give up with a short buffer
            break
        buf.extend(chunk)
    return bytes(buf)


def sync_to_magic(port, magic):
    """Slide a window over the stream until the magic bytes appear."""
    window = bytearray()
    while True:
        b = port.read(1)
        if not b:                # timed out before we ever saw the magic
            return False
        window.extend(b)
        if len(window) > len(magic):
            del window[0]        # keep only the last len(magic) bytes
        if window == magic:
            return True


def read_report(port, overall_timeout=8.0):
    """
    Read the localizer's text report that the board prints after the raw dump.

    The firmware sends the WAV4 payload first and only then the report, so by
    the time this is called the audio is already safely read and nothing here
    can corrupt it. Reading it matters because only one process can hold the
    COM port: without this you would have to choose between capturing the data
    and seeing the board's own answer.

    Stops at the report's "--- end ---" marker, or when the board goes quiet,
    or at overall_timeout. Returns a list of lines, empty if the firmware
    produced nothing (an older build, or Localize_Init having failed).
    """
    previous_timeout = port.timeout
    port.timeout = 0.5              # short, so silence is detected quickly
    lines = []
    deadline = time.time() + overall_timeout
    try:
        while time.time() < deadline:
            raw = port.readline()
            if not raw:
                if lines:
                    break           # it spoke, then stopped: report is done
                continue            # still thinking, keep waiting
            line = raw.decode("ascii", errors="replace").rstrip("\r\n")
            lines.append(line)
            if "--- end ---" in line:
                break
    finally:
        port.timeout = previous_timeout
    return lines


def write_session_notes():
    """
    Record what the room looked like for this session. Written once when the
    session folder is created, and appended to if you pass --notes again on a
    later run, so the history of a sitting stays in one place.
    """
    path = os.path.join(cp.session_dir(SESSION), "notes.txt")
    fresh = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if fresh:
            f.write(f"session {SESSION}\n")
            f.write("=" * (8 + len(SESSION)) + "\n\n")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        f.write(f"[{stamp}] port {PORT}, {SAMPLE_RATE} Hz, "
                f"{NUM_MICS} mics, geometry {GEOMETRY}\n")
        if args.notes:
            f.write(f"    {args.notes}\n")
        f.write("\n")
    return path


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

    if not sync_to_magic(ser, MAGIC):
        print("Never saw the WAV4 header. Did the recording finish?")
        return None

    length_bytes = read_exact(ser, 4)
    if len(length_bytes) < 4:
        print("Short read on the length field.")
        return None

    nbytes = int.from_bytes(length_bytes, "little")   # per-channel byte count
    nsamples = nbytes // 2
    print(f"Header OK. {NUM_MICS} channels of {nbytes} bytes "
          f"({nsamples} samples each).")

    channels = []
    for m in range(NUM_MICS):
        data = read_exact(ser, nbytes)
        if len(data) < nbytes:
            print(f"Short read on mic{m}: got {len(data)} of {nbytes} bytes.")
            return None
        channels.append(np.frombuffer(data, dtype="<i2"))   # LE int16

        with wave.open(wav_for(m), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(data)

    cap = np.stack(channels, axis=0)
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
    report = read_report(ser)
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
        print("Check this angle now:   python check_sync.py")
        print("                        python localize_capture.py --true-angle "
              f"{args.tag.replace('angle', '').lstrip('0') or '0'}")
        print("When the sweep is done: python plot_validation.py")
else:
    # Legacy single capture: loose mic0.wav.. and capture.npy, overwritten.
    if capture_once(None, 1) is None:
        ser.close()
        raise SystemExit(1)

ser.close()
