from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from app.documents.artifact_store import (
    ArtifactStorageError,
    FilesystemArtifactStore,
    S3ArtifactStore,
    verify_artifact,
)
from app.documents.s3_acceptance import run_s3_storage_acceptance


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[dict[str, object]] = []
        self.available = True
        self.versioning_status = "Enabled"
        self.lifecycle_rules: list[dict[str, object]] = [
            {"Status": "Enabled", "Filter": {"Prefix": "tenant/"}}
        ]

    def put_object(self, **kwargs) -> None:
        self.put_calls.append(kwargs)
        self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))] = bytes(kwargs["Body"])

    def get_object(self, **kwargs) -> dict[str, BytesIO]:
        return {"Body": BytesIO(self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))])}

    def delete_object(self, **kwargs) -> None:
        self.objects.pop((str(kwargs["Bucket"]), str(kwargs["Key"])), None)

    def head_bucket(self, **kwargs) -> None:
        del kwargs
        if not self.available:
            raise RuntimeError("unavailable")

    def head_object(self, **kwargs) -> dict[str, object]:
        key = (str(kwargs["Bucket"]), str(kwargs["Key"]))
        if key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not found"}},
                "HeadObject",
            )
        put = next(call for call in reversed(self.put_calls) if call["Key"] == kwargs["Key"])
        return {
            "ContentLength": len(self.objects[key]),
            "Metadata": put["Metadata"],
            "ServerSideEncryption": put["ServerSideEncryption"],
        }

    def get_bucket_versioning(self, **kwargs) -> dict[str, str]:
        del kwargs
        return {"Status": self.versioning_status}

    def get_bucket_lifecycle_configuration(self, **kwargs) -> dict[str, object]:
        del kwargs
        return {"Rules": self.lifecycle_rules}


def test_filesystem_artifact_store_round_trip_integrity_and_delete(tmp_path):
    store = FilesystemArtifactStore(str(tmp_path / "artifacts"))
    content = "SAP 蓝图交付物".encode()

    assert store.available()
    artifact = store.put(
        export_id="export-01",
        claim_token="claim-01",
        content=content,
        media_type="text/markdown",
    )

    assert artifact.backend == "filesystem"
    assert artifact.key == "export-01/claim-01.artifact"
    stored = store.get(artifact.key)
    verify_artifact(
        stored,
        expected_length=artifact.content_length,
        expected_sha256=artifact.sha256,
    )
    store.delete(artifact.key)
    with pytest.raises(ArtifactStorageError, match="could not be read"):
        store.get(artifact.key)


def test_filesystem_artifact_store_rejects_path_escape(tmp_path):
    store = FilesystemArtifactStore(str(tmp_path / "artifacts"))

    with pytest.raises(ArtifactStorageError, match="escapes"):
        store.get("../outside")
    with pytest.raises(ArtifactStorageError, match="invalid"):
        store.get("folder\\outside")


def test_artifact_integrity_rejects_length_and_checksum_mismatch():
    with pytest.raises(ArtifactStorageError, match="length"):
        verify_artifact(b"abc", expected_length=4, expected_sha256=None)
    with pytest.raises(ArtifactStorageError, match="checksum"):
        verify_artifact(b"abc", expected_length=3, expected_sha256="0" * 64)


def test_s3_artifact_store_uses_encryption_metadata_and_prefix():
    client = FakeS3Client()
    store = S3ArtifactStore(
        bucket="blueprints",
        prefix="tenant/exports",
        client=client,
    )

    artifact = store.put(
        export_id="export-01",
        claim_token="claim-01",
        content=b"artifact",
        media_type="application/octet-stream",
    )

    assert artifact.key == "tenant/exports/export-01/claim-01.artifact"
    assert client.put_calls[0]["ServerSideEncryption"] == "AES256"
    assert client.put_calls[0]["Metadata"] == {"sha256": artifact.sha256}
    assert store.get(artifact.key) == b"artifact"
    assert store.available()
    client.available = False
    assert not store.available()
    store.delete(artifact.key)
    assert client.objects == {}

    with pytest.raises(ArtifactStorageError, match="outside"):
        store.get("other-tenant/export-01/claim-01.artifact")


def test_s3_acceptance_checks_round_trip_encryption_versioning_lifecycle_and_delete():
    client = FakeS3Client()
    store = S3ArtifactStore(bucket="blueprints", prefix="tenant/exports", client=client)

    report = run_s3_storage_acceptance(store)

    assert report["status"] == "passed"
    assert report["server_side_encryption"] == "AES256"
    assert report["versioning"] == "Enabled"
    assert report["lifecycle_coverage"] is True
    assert report["delete_confirmed"] is True
    assert report["bucket_ref"].startswith("sha256:")
    assert report["prefix_ref"].startswith("sha256:")
    assert report["lifecycle_rule_refs"]
    assert "blueprints" not in str(report)
    assert "tenant/exports" not in str(report)
    assert "tenant/" not in str(report)
    assert "delete marker" in str(report["versioned_cleanup_note"])
    assert client.objects == {}


@pytest.mark.parametrize(
    ("versioning", "lifecycle_rules", "error"),
    [
        ("Suspended", [{"Status": "Enabled", "Filter": {"Prefix": "tenant/"}}], "versioning"),
        ("Enabled", [{"Status": "Enabled", "Filter": {"Prefix": "other/"}}], "lifecycle"),
    ],
)
def test_s3_acceptance_rejects_missing_retention_guards_and_cleans_probe(
    versioning,
    lifecycle_rules,
    error,
):
    client = FakeS3Client()
    client.versioning_status = versioning
    client.lifecycle_rules = lifecycle_rules
    store = S3ArtifactStore(bucket="blueprints", prefix="tenant/exports", client=client)

    with pytest.raises(ArtifactStorageError, match=error):
        run_s3_storage_acceptance(store)

    assert client.objects == {}
