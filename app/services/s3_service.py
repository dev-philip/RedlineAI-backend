# app/services/s3_service.py
import os, uuid, mimetypes
from typing import Optional, Iterator, Dict, Any, Tuple
from starlette.concurrency import run_in_threadpool
import boto3
from botocore.config import Config
from botocore.client import BaseClient


class S3Service:
    def __init__(
        self,
        client: BaseClient,
        bucket: str,
        prefix: str = "",
        region: str = "us-east-1",
    ):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + ("/" if prefix and not prefix.endswith("/") else "")
        self.region = region

    # ---------- helpers ----------
    def _gen_key(self, filename: Optional[str]) -> str:
        ext = os.path.splitext(filename or "")[1]
        return f"{self.prefix}{uuid.uuid4().hex}{ext}"

    def _guess_content_type(self, filename: Optional[str], fallback="application/octet-stream") -> str:
        return mimetypes.guess_type(filename or "")[0] or fallback

    @staticmethod
    def _extract_key_and_bucket(key_or_url: str) -> Tuple[str, Optional[str]]:
        """
        Accepts:
          - 'redlineai/uploads/abc.pdf'  -> ('redlineai/uploads/abc.pdf', None)
          - '/redlineai/uploads/abc.pdf' -> ('redlineai/uploads/abc.pdf', None)
          - 's3://bucket/redlineai/uploads/abc.pdf' -> ('redlineai/uploads/abc.pdf', 'bucket')
        """
        if not key_or_url:
            return "", None
        if key_or_url.startswith("s3://"):
            # s3://<bucket>/<key...>
            rest = key_or_url[len("s3://") :]
            parts = rest.split("/", 1)
            if len(parts) == 1:
                return "", parts[0] or None
            bucket, key = parts[0], parts[1]
            return key.lstrip("/"), bucket or None
        return key_or_url.lstrip("/"), None

    # ---------- operations ----------
    async def upload_fileobj(
        self,
        file,
        filename: str,
        content_type: Optional[str] = None,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> Dict[str, Any]:
        # optional size check if UploadFile provides .size
        size = getattr(file, "size", None)
        if size and size > max_bytes:
            raise ValueError("File too large")

        key = self._gen_key(filename)
        ct = content_type or self._guess_content_type(filename)

        # If it's a Starlette UploadFile, make sure we're at position 0
        if hasattr(file, "seek"):
            try:
                # UploadFile.seek is async, file.file.seek is sync—handle both
                await file.seek(0)  # type: ignore[attr-defined]
            except TypeError:
                # Not an async seek; ignore
                pass
            except Exception:
                pass

        await run_in_threadpool(
            self.client.upload_fileobj,
            Fileobj=file.file if hasattr(file, "file") else file,  # supports UploadFile or raw file-like
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": ct, "ACL": "private"},
        )

        return {
            "bucket": self.bucket,
            "key": key,
            "region": self.region,
            "url": f"s3://{self.bucket}/{key}",
            "content_type": ct,
        }

    def presign_get_url(
        self,
        key_or_url: str,
        expires_in: int = 300,
        download: bool = False,
        filename: Optional[str] = None,
        response_content_type: Optional[str] = None,
    ) -> str:
        """
        Synchronous presign. Accepts plain key or s3://bucket/key.
        """
        key, bucket_override = self._extract_key_and_bucket(key_or_url)
        if not key:
            raise ValueError("Missing key")

        bucket = bucket_override or self.bucket
        safe_name = filename or os.path.basename(key) or "file"
        disposition = "attachment" if download else "inline"

        params = {
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'{disposition}; filename="{safe_name}"',
        }
        if response_content_type:
            params["ResponseContentType"] = response_content_type

        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=int(expires_in),
        )

    async def generate_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        download: bool = False,
        filename: Optional[str] = None,
        response_content_type: Optional[str] = None,
    ) -> str:
        """
        Async wrapper used by your router. Delegates to presign_get_url in a thread.
        """
        return await run_in_threadpool(
            self.presign_get_url,
            key,
            expires_in,
            download,
            filename,
            response_content_type,
        )

    def get_object(self, key_or_url: str):
        key, bucket_override = self._extract_key_and_bucket(key_or_url)
        bucket = bucket_override or self.bucket
        return self.client.get_object(Bucket=bucket, Key=key)

    @staticmethod
    def iter_body(body, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk


# Factory (dependency)
def build_s3_service() -> S3Service:
    bucket = os.environ["S3_BUCKET_NAME"]
    prefix = os.getenv("S3_PREFIX", "")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    client = boto3.client(
        "s3",
        region_name=region,
        config=Config(s3={"addressing_style": "virtual"}),
    )
    return S3Service(client=client, bucket=bucket, prefix=prefix, region=region)
