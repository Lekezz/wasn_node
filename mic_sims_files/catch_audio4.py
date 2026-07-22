import sys
import serial
import wave
import numpy as np

# 4-channel capture. The firmware dumps, in order:
#   8-byte header: b"WAV4" + 4-byte little-endian per-channel byte count
#   then the four channels back to back (mic0, mic1, mic2, mic3),
#   each one that many bytes of raw int16 samples.
# We sync on the "WAV4" magic instead of reading a fixed count, so any
# boot text or partial buffer left in the stream is skipped cleanly.

# Port defaults to COM4; override it without editing this file by passing it
# on the command line, e.g.  python catch_audio4.py COM7
PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
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


ser.reset_input_buffer()         # throw away the welcome message etc.
print("Ready. Press the blue button on the board now...")

if not sync_to_magic(ser, MAGIC):
    print("Never saw the WAV4 header. Did the recording finish? Try again.")
    ser.close()
    raise SystemExit(1)

length_bytes = read_exact(ser, 4)
if len(length_bytes) < 4:
    print("Short read on the length field. Try again.")
    ser.close()
    raise SystemExit(1)

nbytes = int.from_bytes(length_bytes, "little")   # per-channel byte count
nsamples = nbytes // 2
print(f"Header OK. Expecting {NUM_MICS} channels of {nbytes} bytes "
      f"({nsamples} samples each).")

channels = []
for m in range(NUM_MICS):
    data = read_exact(ser, nbytes)
    if len(data) < nbytes:
        print(f"Short read on mic{m}: got {len(data)} of {nbytes} bytes. "
              f"Try again.")
        ser.close()
        raise SystemExit(1)
    samples = np.frombuffer(data, dtype="<i2")    # little-endian int16
    channels.append(samples)

    with wave.open(f"mic{m}.wav", "wb") as w:
        w.setnchannels(1)        # mono, one file per mic
        w.setsampwidth(2)        # 16-bit
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data)
    print(f"Saved mic{m}.wav")

# Stack into a (NUM_MICS, nsamples) array for the localization code.
capture = np.stack(channels, axis=0)
np.save("capture.npy", capture)
print(f"Saved capture.npy with shape {capture.shape}")

ser.close()
