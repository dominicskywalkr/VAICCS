import numpy as np
import soundfile as sf
from voice_profiles import VoiceProfileManager
import os

OUT = os.path.dirname(__file__)

def make_sine(path, freq=440.0, dur=1.0, sr=16000):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    x = 0.2 * np.sin(2 * np.pi * freq * t)
    sf.write(path, x, sr)


def main():
    a = os.path.join(OUT, "test_a.wav")
    b = os.path.join(OUT, "test_b.wav")
    unk = os.path.join(OUT, "test_unknown.wav")
    make_sine(a, freq=440.0)
    make_sine(b, freq=445.0)
    make_sine(unk, freq=441.0)

    mgr = VoiceProfileManager()
    print("Existing profiles:", mgr.list_profiles())
    # ensure clean state for test
    if "test_speaker" in mgr.list_profiles():
        mgr.delete_profile("test_speaker")
    meta = mgr.create_profile("test_speaker", [a, b])
    print("Created profile:", meta)
    res = mgr.match_profile(unk, top_k=3)
    print("Match results:", res)


if __name__ == '__main__':
    main()
