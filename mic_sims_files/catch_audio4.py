import argparse
import glob
import os
import re
import serial
import wave
import numpy as np

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
                    help="filename prefix so a run does not overwrite the "
                         "last. During an angle sweep use the true angle, "
                         "e.g. --tag angle090. Files are then named per "
                         "trial: angle090_trial1_capture.npy and so on. "
                         "Without --tag, files are the old mic0.wav.. and "
                         "capture.npy, overwritten each run.")
parser.add_argument("--trials", type=int, default=1,
                    help="how many recordings to take in a row at this angle "
                         "(default 1). Each one waits for its own button "
                         "press. Trial numbers continue past any files "
                         "already saved for this tag, so you can also just "
                         "rerun the command to add more.")
args = parser.parse_args()

if args.trials < 1:
    parser.error("--trials must be at least 1")
if args.trials > 1 and not args.tag:
    parser.error("--trials needs --tag so the recordings get distinct names")

PORT = args.port
BAUD = 115200
SAMPLE_RATE = 16000
NUM_MICS = 4
MAGIC = b"WAV4"

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


def next_trial_number(tag):
    """
    First unused trial index for this tag, so separate runs keep adding
    instead of overwriting. Scans existing <tag>_trial<K>_capture.npy.
    """
    highest = 0
    for path in glob.glob(f"{tag}_trial*_capture.npy"):
        m = re.search(rf"{re.escape(tag)}_trial(\d+)_capture\.npy$",
                      os.path.basename(path))
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def capture_once(prefix):
    """
    Wait for one button press, read the four channels, save them.
    Returns the (NUM_MICS, nsamples) array, or None on any read failure.
    """
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

        wav_name = f"{prefix}mic{m}.wav"
        with wave.open(wav_name, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(data)

    cap = np.stack(channels, axis=0)
    npy_name = f"{prefix}capture.npy"
    np.save(npy_name, cap)

    # Quick quality hint so a dud trial gets caught now, not at plot time.
    peak = int(np.max(np.abs(cap)))
    if peak >= 32700:
        note = "  WARNING: clipped, clap softer or further"
    elif peak < 2000:
        note = "  WARNING: very quiet, clap harder or closer"
    else:
        note = ""
    print(f"Saved {npy_name} (peak {peak} of 32767){note}")
    return cap


if args.tag:
    start = next_trial_number(args.tag)
    saved = 0
    for i in range(args.trials):
        k = start + i
        print(f"\n=== {args.tag}  trial {k}  ({i + 1} of {args.trials}) ===")
        if capture_once(f"{args.tag}_trial{k}_") is None:
            print("Stopping this angle. Rerun to continue from where it left "
                  "off.")
            break
        saved += 1
    print(f"\nDone. Saved {saved} trial(s) for {args.tag}.")
    if saved:
        print("When the whole sweep is done, plot it with: "
              "python plot_validation.py")
else:
    # Legacy single capture: mic0.wav.. and capture.npy, overwritten.
    if capture_once("") is None:
        ser.close()
        raise SystemExit(1)

ser.close()
