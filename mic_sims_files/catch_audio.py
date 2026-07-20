import serial
import wave

PORT = "COM4"          # change to your port from Device Manager
BAUD = 115200
SAMPLE_RATE = 16000
SECONDS = 4
NBYTES = SAMPLE_RATE * SECONDS * 2   # 2 bytes per 16-bit sample

ser = serial.Serial(PORT, BAUD, timeout=90)
ser.reset_input_buffer()             # throw away the welcome message etc.
print("Ready. Press the blue button on the board now...")

data = ser.read(NBYTES)
print(f"Received {len(data)} of {NBYTES} bytes")

if len(data) < NBYTES:
    print("Short read. Did the recording finish? Try again.")
else:
    with wave.open("recording.wav", "wb") as w:
        w.setnchannels(1)      # mono
        w.setsampwidth(2)      # 16-bit
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data)
    print("Saved recording.wav")

ser.close()