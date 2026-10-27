"""List the sentences to record for the demo (convoy notes and handler answers).

Usage: python new/scripts/recording_list.py [DEV-02 DEV-07 ...] > recordings.md

Record each sentence (phone voice memo is fine), name the file <id>.m4a and drop it in the
dossier's voice/audio/ folder, e.g. new/bench/dev/DEV-02/voice/audio/H1.m4a. In live mode the
agent then transcribes the recording with Muse Voice Transcribe instead of using the text.
"""
import sys

import _path  # noqa: F401
from lcw import BENCH_DIR
from lcw.dossier import Dossier


def main() -> None:
    wanted = set(sys.argv[1:])
    print("| Dossier | File | Who | Sentence |\n| --- | --- | --- | --- |")
    for folder in sorted(p for p in (BENCH_DIR / "dev").iterdir() if (p / "dossier.json").exists()):
        if wanted and folder.name not in wanted:
            continue
        dossier = Dossier(folder)
        for note in dossier.convoy_notes():
            print(f"| {dossier.id} | voice/audio/{note['id']}.m4a | convoy attendant | {note['text']} |")
        for answer in dossier.handler_answers():
            if not answer.get("default"):
                print(f"| {dossier.id} | voice/audio/{answer['id']}.m4a | ground handler | {answer['answer']} |")


if __name__ == "__main__":
    main()
