"""Pre-push check: run before every push and before the submission.

Usage: python new/scripts/check_release.py [--fast] [--outputs DIR]
  --fast          skips ruff and pytest
  --outputs DIR   also scans a run's output folder (cases/, results/) — CA-13 on the bench outputs

Checks the files git tracks (what the judges will see), never the reserved bench's content:
  1. ruff and the offline test suite pass;
  2. no secret: .env not tracked, no key-shaped value in tracked files;
  3. no private name (shipper, carrier, handler): names listed one per line in the git-ignored
     file .private-names at the repository root — the list itself never enters the repo;
  4. the reserved bench is untouched: only its README, the encrypted archive and the seal are
     tracked, unchanged since the commit that sealed them;
  5. synthetic data is labelled (dossier.json, curves, truth files);
  6. IATA wording and vocabulary rules in the public texts;
  7. no dry-run output is tracked.
Exit code 1 if any check fails. Warnings (e.g. a private name in an old commit message) do not fail.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import _path  # noqa: F401
from lcw import NEW_DIR
from lcw.vocab import find_forbidden

REPO = NEW_DIR.parent
SEAL_COMMIT_MESSAGE = "Seal the reserved bench"
RESERVED_TRACKED = {"new/bench/reserved/README.md", "new/bench/reserved.tar.gz.enc", "new/bench/reserved.seal"}
RESERVED_ALLOWED = RESERVED_TRACKED | {"new/bench/reserved/.gitkeep"}
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-.]{20,}"),
]
IATA_FORBIDDEN = re.compile(r"(?i)IATA[- ]?(specialist|certified|approved|expert)|(certified|approved) by IATA")
# Files that state the rules themselves (they must quote the forbidden words).
RULE_TEXTS = {"CLAUDE.md", "new/lcw/vocab.py", "new/lcw/prompts.py", "new/scripts/check_release.py",
              "new/tests/test_vocab.py", "new/tests/test_verifier.py", "new/tests/test_agent_robustness.py"}
PUBLIC_TEXTS = ("README.md", "new/rules/", "new/bench/FORMAT.md", "new/bench/reserved/README.md")
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".csv", ".txt", ".toml", ".html", ".cfg", ".ini", ""}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout


def tracked() -> list[str]:
    return [line for line in git("ls-files").splitlines() if line]


def text_of(path: str) -> str | None:
    file = REPO / path
    if file.suffix not in TEXT_SUFFIXES or not file.is_file():
        return None
    try:
        return file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


class Report:
    def __init__(self):
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, title: str, problems: list[str]) -> None:
        print(f"[{'FAIL' if problems else ' ok '}] {title}")
        for problem in problems[:20]:
            print(f"        {problem}")
        if len(problems) > 20:
            print(f"        ... and {len(problems) - 20} more")
        self.failures += problems

    def warn(self, message: str) -> None:
        print(f"[warn] {message}")
        self.warnings.append(message)


def check_tools(report: Report) -> None:
    for title, command in (("ruff check new", [sys.executable, "-m", "ruff", "check", "new"]),
                           ("pytest new/tests", [sys.executable, "-m", "pytest", "new/tests", "-q"])):
        done = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        tail = (done.stdout + done.stderr).strip().splitlines()[-5:]
        report.check(title, [] if done.returncode == 0 else tail)


def check_secrets(report: Report, files: list[str]) -> None:
    problems = [".env is tracked"] if ".env" in files else []
    for path in files:
        text = text_of(path)
        if text is None:
            continue
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{path}:{line}: key-shaped value")
    report.check("no secret in tracked files", problems)


def private_name_patterns() -> list[re.Pattern] | None:
    names_file = REPO / ".private-names"
    if not names_file.exists():
        return None
    names = [n.strip() for n in names_file.read_text(encoding="utf-8").splitlines()
             if n.strip() and not n.startswith("#")]
    return [re.compile(r"(?i)\b" + re.escape(n) + r"\b") for n in names]


def check_outputs(report: Report, folder: Path) -> None:
    """CA-13 on what the agent produced: no forbidden word in the records, no private name anywhere."""
    if not folder.is_dir():
        report.check(f"outputs in {folder}", [f"{folder} is not a folder"])
        return
    patterns = private_name_patterns() or []
    if not patterns:
        report.warn(".private-names is missing: private names not checked in the outputs")
    problems = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix in (".json", ".md", ".html")):
        relative = path.relative_to(folder).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            problems.append(f"{relative}: contains a private name")
        if relative.startswith("cases/") and find_forbidden(text):
            problems.append(f"{relative}: forbidden vocabulary {find_forbidden(text)}")
    report.check(f"outputs of {folder.name}: no private name, no forbidden word in records", problems)


def check_private_names(report: Report, files: list[str]) -> None:
    names_file = REPO / ".private-names"
    if not names_file.exists():
        report.warn(".private-names is missing: private-name check skipped (create it, one name per line)")
        return
    if ".private-names" in files:
        report.check("private names", [".private-names is tracked: remove it from git"])
        return
    names = [n.strip() for n in names_file.read_text(encoding="utf-8").splitlines()
             if n.strip() and not n.startswith("#")]
    patterns = [re.compile(r"(?i)\b" + re.escape(n) + r"\b") for n in names]
    problems = []
    for path in files:
        text = text_of(path)
        if text is None:
            continue
        for pattern in patterns:
            if pattern.search(text) or pattern.search(path):
                problems.append(f"{path}: contains a private name")
    report.check(f"no private name in tracked files ({len(names)} names checked)", problems)
    history = git("log", "--all", "-p", "--format=%H %s")
    for pattern in patterns:
        if pattern.search(history):
            report.warn("a private name appears in the git history (an old commit): rewriting history "
                        "needs Maxime's explicit approval")
            break


def check_reserved(report: Report, files: list[str]) -> None:
    problems = [f"tracked reserved file not expected: {p}" for p in files
                if p.startswith("new/bench/reserved") and p not in RESERVED_ALLOWED]
    problems += [f"missing: {p}" for p in RESERVED_TRACKED if p not in files]
    sealed = [line.split()[0] for line in git("log", "--format=%H %s").splitlines()
              if SEAL_COMMIT_MESSAGE in line]
    if not sealed:
        problems.append("the sealing commit was not found")
    else:
        sealed_files = sorted(RESERVED_TRACKED - {"new/bench/reserved/README.md"})
        changed = git("diff", "--name-only", sealed[-1], "--", *sealed_files)
        problems += [f"changed since sealing: {p}" for p in changed.split()]
    plain = [p for p in (REPO / "new/bench/reserved").rglob("*")
             if p.is_file() and p.name not in ("README.md", ".gitkeep")]
    problems += [f"plaintext reserved file on disk: {p.relative_to(REPO)}" for p in plain]
    report.check("reserved bench sealed and untouched", problems)


def check_synthetic(report: Report, files: list[str]) -> None:
    problems = []
    for path in files:
        if not path.startswith(("new/bench/dev/", "new/bench/demo/")):
            continue
        if path.endswith(("dossier.json", ".truth.json", "expected.json", "convoy_notes.json")):
            data = json.loads((REPO / path).read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("synthetic") is not True:
                problems.append(f"{path}: synthetic is not true")
        elif path.endswith("curve.csv"):
            first = (REPO / path).read_text(encoding="utf-8").splitlines()[0]
            if not first.startswith("# SYNTHETIC"):
                problems.append(f"{path}: first line is not '# SYNTHETIC'")
    report.check("synthetic data labelled", problems)


def check_wording(report: Report, files: list[str]) -> None:
    problems = []
    for path in files:
        text = text_of(path)
        if text is None or path in RULE_TEXTS or path.startswith(".claude/"):
            continue
        if IATA_FORBIDDEN.search(text):
            problems.append(f"{path}: IATA wording (say 'built for live-animal shipments subject to the IATA LAR')")
        if path.startswith(PUBLIC_TEXTS):
            forbidden = find_forbidden(text)
            if forbidden:
                problems.append(f"{path}: forbidden vocabulary {forbidden}")
    report.check("IATA wording and vocabulary", problems)


def check_no_dry_run(report: Report, files: list[str]) -> None:
    problems = [p for p in files if p.startswith("new/results/") and not p.endswith(".gitkeep")]
    for path in files:
        if path.startswith("new/tests/") or path == "new/scripts/check_release.py":
            continue
        text = text_of(path) or ""
        if "scripted test client (not a model)" in text:
            problems.append(f"{path}: contains output of the scripted test client")
    report.check("no dry-run output tracked", problems)


def main() -> None:
    report = Report()
    files = tracked()
    if "--fast" not in sys.argv:
        check_tools(report)
    check_secrets(report, files)
    check_private_names(report, files)
    check_reserved(report, files)
    check_synthetic(report, files)
    check_wording(report, files)
    check_no_dry_run(report, files)
    if "--outputs" in sys.argv:
        index = sys.argv.index("--outputs") + 1
        if index >= len(sys.argv):
            raise SystemExit("--outputs needs a folder")
        check_outputs(report, Path(sys.argv[index]).resolve())
    print(f"\n{'FAIL' if report.failures else 'OK'}: {len(report.failures)} problem(s), "
          f"{len(report.warnings)} warning(s)")
    sys.exit(1 if report.failures else 0)


if __name__ == "__main__":
    main()
