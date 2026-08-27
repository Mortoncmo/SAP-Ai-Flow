import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.core.config import Settings


class ArtifactStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    backend: str
    key: str
    content_length: int
    sha256: str


class ArtifactStore(Protocol):
    backend: str

    def put(
        self,
        *,
        export_id: str,
        claim_token: str,
        content: bytes,
        media_type: str,
    ) -> StoredArtifact: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def available(self) -> bool: ...


def artifact_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_artifact(
    content: bytes,
    *,
    expected_length: int | None,
    expected_sha256: str | None,
) -> None:
    if expected_length is not None and len(content) != expected_length:
        raise ArtifactStorageError("artifact length does not match persisted metadata")
    if expected_sha256 is not None and artifact_sha256(content) != expected_sha256:
        raise ArtifactStorageError("artifact checksum does not match persisted metadata")


def _artifact_key(export_id: str, claim_token: str, *, prefix: str = "") -> str:
    segment_pattern = re.compile(r"^[A-Za-z0-9._-]+$")
    if not segment_pattern.fullmatch(export_id) or not segment_pattern.fullmatch(claim_token):
        raise ArtifactStorageError("artifact identifier contains unsupported characters")
    relative_key = f"{export_id}/{claim_token}.artifact"
    return f"{prefix.rstrip('/')}/{relative_key}" if prefix else relative_key


class FilesystemArtifactStore:
    backend = "filesystem"

    def __init__(self, root: str) -> None:
        if not root.strip():
            raise ArtifactStorageError("filesystem artifact root is not configured")
        self.root = Path(root).expanduser().resolve()

    def put(
        self,
        *,
        export_id: str,
        claim_token: str,
        content: bytes,
        media_type: str,
    ) -> StoredArtifact:
        del media_type
        key = _artifact_key(export_id, claim_token)
        target = self._resolve_key(key)
        temp_path: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=".artifact-",
                delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, target)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise ArtifactStorageError("artifact could not be written") from exc
        return StoredArtifact(
            backend=self.backend,
            key=key,
            content_length=len(content),
            sha256=artifact_sha256(content),
        )

    def get(self, key: str) -> bytes:
        try:
            return self._resolve_key(key).read_bytes()
        except OSError as exc:
            raise ArtifactStorageError("artifact could not be read") from exc

    def delete(self, key: str) -> None:
        target = self._resolve_key(key)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise ArtifactStorageError("artifact could not be deleted") from exc
        if target.parent != self.root:
            try:
                target.parent.rmdir()
            except OSError:
                pass

    def available(self) -> bool:
        probe_path: Path | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(
                dir=self.root,
                prefix=".health-",
                delete=False,
            ) as probe:
                probe_path = Path(probe.name)
                probe.write(b"ok")
                probe.flush()
                os.fsync(probe.fileno())
            return probe_path.read_bytes() == b"ok"
        except OSError:
            return False
        finally:
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)

    def _resolve_key(self, key: str) -> Path:
        if not key or "\\" in key:
            raise ArtifactStorageError("artifact key is invalid")
        candidate = (self.root / key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactStorageError("artifact key escapes the configured root") from exc
        return candidate


class S3ArtifactStore:
    backend = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str = "",
        endpoint_url: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        client: Any | None = None,
    ) -> None:
        if not bucket.strip():
            raise ArtifactStorageError("S3 artifact bucket is not configured")
        self.bucket = bucket.strip()
        self.prefix = prefix.strip().strip("/")
        if client is None:
            try:
                import boto3
                from botocore.config import Config

                client = boto3.client(
                    "s3",
                    region_name=region.strip() or None,
                    endpoint_url=endpoint_url.strip() or None,
                    aws_access_key_id=access_key_id or None,
                    aws_secret_access_key=secret_access_key or None,
                    config=Config(s3={"addressing_style": "path"}),
                )
            except Exception as exc:
                raise ArtifactStorageError("S3 artifact client could not be configured") from exc
        self.client = client

    def put(
        self,
        *,
        export_id: str,
        claim_token: str,
        content: bytes,
        media_type: str,
    ) -> StoredArtifact:
        key = _artifact_key(export_id, claim_token, prefix=self.prefix)
        digest = artifact_sha256(content)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=media_type,
                Metadata={"sha256": digest},
                ServerSideEncryption="AES256",
            )
        except Exception as exc:
            raise ArtifactStorageError("artifact could not be uploaded to S3") from exc
        return StoredArtifact(
            backend=self.backend,
            key=key,
            content_length=len(content),
            sha256=digest,
        )

    def get(self, key: str) -> bytes:
        self._validate_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                return body.read()
            finally:
                close = getattr(body, "close", None)
                if close is not None:
                    close()
        except Exception as exc:
            raise ArtifactStorageError("artifact could not be downloaded from S3") from exc

    def delete(self, key: str) -> None:
        self._validate_key(key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise ArtifactStorageError("artifact could not be deleted from S3") from exc

    def available(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            return False
        return True

    def _validate_key(self, key: str) -> None:
        parts = key.split("/")
        if (
            not key
            or key.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or (self.prefix and not key.startswith(f"{self.prefix}/"))
        ):
            raise ArtifactStorageError("artifact key is outside the configured S3 prefix")


def build_artifact_store(settings: "Settings") -> ArtifactStore | None:
    return _build_artifact_store(
        settings.export_storage_backend,
        settings.export_storage_path,
        settings.export_s3_bucket,
        settings.export_s3_prefix,
        settings.export_s3_region,
        settings.export_s3_endpoint_url,
        settings.export_s3_access_key_id,
        settings.export_s3_secret_access_key,
    )


@lru_cache(maxsize=8)
def _build_artifact_store(
    backend: str,
    storage_path: str,
    s3_bucket: str,
    s3_prefix: str,
    s3_region: str,
    s3_endpoint_url: str,
    s3_access_key_id: str,
    s3_secret_access_key: str,
) -> ArtifactStore | None:
    if backend == "database":
        return None
    if backend == "filesystem":
        return FilesystemArtifactStore(storage_path)
    return S3ArtifactStore(
        bucket=s3_bucket,
        prefix=s3_prefix,
        region=s3_region,
        endpoint_url=s3_endpoint_url,
        access_key_id=s3_access_key_id,
        secret_access_key=s3_secret_access_key,
    )
