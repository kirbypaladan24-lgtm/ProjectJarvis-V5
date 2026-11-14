import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from faster_whisper import WhisperModel

model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=6)

def record_audio(duration=5, fs=16000):
    print("🎤 Speak now...")
    audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
    sd.wait()
    write("input.wav", fs, audio)
    return "input.wav"

def speech_to_text():
    audio_file = record_audio()
    segments, _ = model.transcribe(audio_file)

    text = ""
    for segment in segments:
        text += segment.text + " "

    return text.strip()

print("Say something...")
print("You said:", speech_to_text())