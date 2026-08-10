import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from botocore.exceptions import ClientError

from app.documents.artifact_store import (
    ArtifactStorageError,
    S3ArtifactStore,
    StoredArtifact,
    verify_artifact,
)

PROBE_CONTENT = b"SAP AI Flow S3 acceptance probe\n"


def run_s3_storage_acceptance(store: S3ArtifactStore) -> dict[str, object]:
    if not store.available():
        raise ArtifactStorageError("S3 bucket is unavailable to the configured identity")

    suffix = uuid4().hex
    stored: StoredArtifact | None = None
    head: dict[str, Any]
    versioning_status: str
    lifecycle_prefixes: list[str]
    try:
        stored = store.put(
            export_id=f"s3-acceptance-{suffix}",
            claim_token=f"probe-{suffix}",
            content=PROBE_CONTENT,
            media_type="application/octet-stream",
        )
        downloaded = store.get(stored.key)
        verify_artifact(
            downloaded,
            expected_length=stored.content_length,
            expected_sha256=stored.sha256,
        )
        head = _head_object(store, stored.key)
        if head.get("ServerSideEncryption") != "AES256":
            raise ArtifactStorageError("S3 probe object is not protected by AES256 SSE")
        metadata = head.get("Metadata")
        if not isinstance(metadata, dict) or metadata.get("sha256") != stored.sha256:
            raise ArtifactStorageError("S3 probe object checksum metadata is missing")
        if int(head.get("ContentLength", -1)) != stored.content_length:
            raise ArtifactStorageError("S3 probe object length metadata does not match")

        versioning_status = _versioning_status(store)
        if versioning_status != "Enabled":
            raise ArtifactStorageError("S3 bucket versioning is not enabled")
        lifecycle_prefixes = _lifecycle_prefixes(store)
        if not _prefix_is_covered(store.prefix, lifecycle_prefixes):
            raise ArtifactStorageError("S3 lifecycle does not cover the configured artifact prefix")
    finally:
        if stored is not None:
            store.delete(stored.key)

    if _object_exists(store, stored.key):
        raise ArtifactStorageError("S3 probe object is still readable after deletion")

    return {
        "status": "passed",
        "checked_at": datetime.now(UTC).isoformat(),
        "bucket_ref": _redacted_target_ref(store.bucket),
        "prefix_ref": _redacted_target_ref(store.prefix),
        "round_trip_verified": True,
        "server_side_encryption": "AES256",
        "checksum_metadata_verified": True,
        "content_length": stored.content_length,
        "versioning": versioning_status,
        "lifecycle_coverage": True,
        "lifecycle_rule_refs": [
            _redacted_target_ref(rule_prefix) for rule_prefix in lifecycle_prefixes
        ],
        "delete_confirmed": True,
        "delete_confirmation_scope": "current object is no longer readable",
        "versioned_cleanup_note": (
            "deletion creates a delete marker; noncurrent probe versions remain subject "
            "to the bucket lifecycle and retention policy"
        ),
    }


def _redacted_target_ref(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:12]}"


def _head_object(store: S3ArtifactStore, key: str) -> dict[str, Any]:
    try:
        response = store.client.head_object(Bucket=store.bucket, Key=key)
    except Exception as exc:
        raise ArtifactStorageError("S3 probe object metadata could not be read") from exc
    if not isinstance(response, dict):
        raise ArtifactStorageError("S3 probe object metadata response is invalid")
    return response


def _versioning_status(store: S3ArtifactStore) -> str:
    try:
        response = store.client.get_bucket_versioning(Bucket=store.bucket)
    except Exception as exc:
        raise ArtifactStorageError("S3 bucket versioning could not be inspected") from exc
    return str(response.get("Status", "Disabled"))


def _lifecycle_prefixes(store: S3ArtifactStore) -> list[str]:
    try:
        response = store.client.get_bucket_lifecycle_configuration(Bucket=store.bucket)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"NoSuchLifecycleConfiguration", "NoSuchLifecycle"}:
            return []
        raise ArtifactStorageError("S3 bucket lifecycle could not be inspected") from exc
    except Exception as exc:
        raise ArtifactStorageError("S3 bucket lifecycle could not be inspected") from exc

    prefixes: list[str] = []
    for rule in response.get("Rules", []):
        if not isinstance(rule, dict) or rule.get("Status") != "Enabled":
            continue
        rule_filter = rule.get("Filter")
        if rule_filter is None:
            prefixes.append(str(rule.get("Prefix", "")))
        elif isinstance(rule_filter, dict) and not rule_filter:
            prefixes.append("")
        elif isinstance(rule_filter, dict) and "Prefix" in rule_filter:
            prefixes.append(str(rule_filter["Prefix"]))
        elif isinstance(rule_filter, dict) and isinstance(rule_filter.get("And"), dict):
            compound = rule_filter["And"]
            if "Prefix" in compound:
                prefixes.append(str(compound["Prefix"]))
    return sorted(set(prefixes))


def _prefix_is_covered(configured_prefix: str, lifecycle_prefixes: list[str]) -> bool:
    return any(configured_prefix.startswith(rule_prefix) for rule_prefix in lifecycle_prefixes)


def _object_exists(store: S3ArtifactStore, key: str) -> bool:
    try:
        store.client.head_object(Bucket=store.bucket, Key=key)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise ArtifactStorageError("S3 probe deletion could not be verified") from exc
    except Exception as exc:
        raise ArtifactStorageError("S3 probe deletion could not be verified") from exc
    return True
