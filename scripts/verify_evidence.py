"""Re-verify every scored run published under evidence/5423ab2/.

Usage: py -3 scripts/verify_evidence.py   (exit 0 only if every manifest holds)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from run import SOURCE_PATHS  # noqa: E402
from verify_manifest import recheck  # noqa: E402
from verifier.rules import VERIFIER_VERSION  # noqa: E402

EVIDENCE_DIR = ROOT / "evidence" / "5423ab2"
SOURCE_FILES = {path.resolve().relative_to(ROOT).as_posix() for path in SOURCE_PATHS}
SOURCE_MISMATCH = "MISMATCH (sources changed since 5423ab2: check out 5423ab2 to re-verify)"


def main() -> int:
    manifests = sorted(EVIDENCE_DIR.glob("*/manifest.json"))
    verified = 0
    for manifest_path in manifests:
        problems = recheck(manifest_path)
        if not problems:
            verified += 1
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(f"OK: {len(manifest['files']) + 1} file hashes, {len(manifest['traces'])} traces re-verified, verifier {VERIFIER_VERSION}")
        elif any(problem.split(":", 1)[0] in SOURCE_FILES for problem in problems):
            print(SOURCE_MISMATCH)
        else:
            print("MISMATCH")
    print(f"OK {verified} of {len(manifests)}")
    return 0 if manifests and verified == len(manifests) else 1


if __name__ == "__main__":
    sys.exit(main())
