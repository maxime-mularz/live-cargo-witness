"""List the sentences to record for the demo (convoy notes and handler answers).

Usage: python new/scripts/recording_list.py [DEMO-02 DEV-02 ...] > recordings.md

Covers bench/demo and bench/dev. Record each sentence (phone voice memo is fine) and save it at
the path given, e.g. new/bench/demo/DEMO-02/voice/audio/H1.m4a. A .m4a (or .mp3, .ogg, .webm)
needs ffmpeg to be converted; a 16 kHz mono 16-bit WAV with the same name (H1.wav) is sent as
is. In live mode the agent then transcribes the recording with Muse Voice Transcribe instead of
using the text.
"""
import sys

import _path  # noqa: F401
from lcw import BENCH_DIR, NEW_DIR
from lcw.dossier import Dossier


def main() -> None:
    wanted = set(sys.argv[1:])
    print("| Dossier | File | Who | Sentence |\n| --- | --- | --- | --- |")
    folders = [p for bench in ("demo", "dev") for p in sorted((BENCH_DIR / bench).iterdir())
               if (p / "dossier.json").exists()]
    for folder in folders:
        if wanted and folder.name not in wanted:
            continue
        dossier = Dossier(folder)
        audio = (folder / "voice" / "audio").relative_to(NEW_DIR.parent)
        for note in dossier.convoy_notes():
            print(f"| {dossier.id} | {audio}/{note['id']}.m4a | convoy attendant | {note['text']} |")
        for answer in dossier.handler_answers():
            if not answer.get("default"):
                print(f"| {dossier.id} | {audio}/{answer['id']}.m4a | ground handler | {answer['answer']} |")


if __name__ == "__main__":
    main()
