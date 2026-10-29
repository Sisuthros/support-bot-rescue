import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence" / "5423ab2"


def test_evidence_has_all_seventeen_scored_manifests():
    manifests = sorted(EVIDENCE_DIR.glob("*/manifest.json"))
    assert len(manifests) == 17
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["git_commit"].startswith("5423ab2")
        assert manifest["git_dirty"] is False
        assert manifest["client"] == "meta"
        for trace in manifest["traces"].values():
            assert (manifest_path.parent / trace["path"]).is_file()
