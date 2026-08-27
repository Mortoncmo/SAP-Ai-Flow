import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.config import get_settings  # noqa: E402
from app.documents.artifact_store import S3ArtifactStore, build_artifact_store  # noqa: E402
from app.documents.s3_acceptance import run_s3_storage_acceptance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a configured production S3 artifact bucket and lifecycle policy."
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="Acknowledge that the check writes and deletes one uniquely named probe object.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "output" / "s3-acceptance" / "report.json"),
    )
    args = parser.parse_args()
    if not args.allow_write:
        parser.error("--allow-write is required before testing a target bucket")

    settings = get_settings()
    if settings.export_storage_backend != "s3":
        parser.error("EXPORT_STORAGE_BACKEND must be s3")
    store = build_artifact_store(settings)
    if not isinstance(store, S3ArtifactStore):
        parser.error("the configured artifact store is not S3")

    report = run_s3_storage_acceptance(store)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
