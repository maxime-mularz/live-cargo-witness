"""Open the reserved bench — AFTER the code freeze only (Nov 3, 2026, 6 PM Paris).

Usage: RESERVED_PASSWORD=... python new/scripts/unseal_bench.py

Decrypts new/bench/reserved.tar.gz.enc into new/bench/reserved/, then checks that the seal of the
extracted dossiers equals the one committed in new/bench/reserved.seal before the freeze.
"""
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import _path  # noqa: F401
from lcw import BENCH_DIR
from lcw.hashing import seal_folder

FREEZE = datetime(2026, 11, 3, 17, 0, tzinfo=timezone.utc)  # 6 PM Paris (UTC+1)


def main() -> None:
    if datetime.now(timezone.utc) < FREEZE and "--i-know-it-is-before-the-freeze" not in sys.argv:
        raise SystemExit("The code freeze has not happened yet. The reserved bench stays sealed.")
    password = os.environ.get("RESERVED_PASSWORD")
    if not password:
        raise SystemExit("Set RESERVED_PASSWORD in the environment (never on the command line).")
    encrypted = BENCH_DIR / "reserved.tar.gz.enc"
    target = BENCH_DIR / "reserved"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "reserved.tar.gz"
        subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                        "-in", str(encrypted), "-out", str(archive), "-pass", "env:RESERVED_PASSWORD"],
                       check=True)
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")
    committed = (BENCH_DIR / "reserved.seal").read_text(encoding="utf-8").split()[0]
    computed = seal_folder(target)
    if computed != committed:
        raise SystemExit(f"SEAL MISMATCH\n committed {committed}\n computed  {computed}")
    print(f"Reserved bench unsealed into {target} — seal matches ({computed}).")


if __name__ == "__main__":
    main()
