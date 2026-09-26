"""Private OSS adapter; credentials stay on the server, legacy config stays valid."""
import hashlib
import urllib.request
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from urllib.parse import quote

from ai_platform.storage import media_oss_config


def shared_storage_config(secrets_data):
    # MEDIA falls back to CAT, the existing shared store. No second credential form.
    config = media_oss_config(secrets_data)
    return {**config, "directory": "share"}


class StorageSecurityError(RuntimeError):
    pass


class PrivateOSS:
    def __init__(self, config):
        self.config = config
        if not config.get("configured"):
            raise ValueError("请先配置现有的通用 OSS 存储")
        if not config["endpoint"].startswith("https://"):
            raise ValueError("文件分享要求 HTTPS OSS Endpoint")

    def signed(self, method, key, query=None, headers=None, ttl=300):
        # Official V4 signer: required by buckets that disable V1 presigned URLs.
        # Existing endpoint is already bucket-qualified (or an OSS CNAME).
        import oss2
        bucket = oss2.Bucket(oss2.AuthV4(self.config["access_key_id"], self.config["access_key_secret"]),
                            self.config["endpoint"], self.config["bucket"],
                            is_cname=True, region=self.config["region"])
        return bucket.sign_url(method, key, ttl, headers=dict(headers or {}),
                               params={k:str(v) for k,v in (query or {}).items()}, slash_safe=True)

    def request(self, method, key, query=None, headers=None, body=None):
        req = urllib.request.Request(self.signed(method, key, query, headers), data=body, headers=headers or {}, method=method)
        return urllib.request.urlopen(req, timeout=45)

    def begin(self, key, content_type="application/octet-stream"):
        with self.request("POST", key, {"uploads": ""}, {"x-oss-object-acl": "private", "Content-Type": content_type, "Cache-Control": "private, no-store"}, b"") as response:
            root = ET.fromstring(response.read(65536))
        return root.findtext("UploadId")

    def complete(self, key, upload_id, parts):
        root = ET.Element("CompleteMultipartUpload")
        for number, etag in parts:
            part = ET.SubElement(root, "Part")
            ET.SubElement(part, "PartNumber").text = str(number)
            ET.SubElement(part, "ETag").text = etag
        with self.request("POST", key, {"uploadId": upload_id}, {"Content-Type": "application/xml", "x-oss-object-acl": "private"}, ET.tostring(root)) as response:
            result = ET.fromstring(response.read(65536))
            if result.tag == "Error":
                raise ValueError("OSS 合并分片失败")

    def head(self, key):
        with self.request("HEAD", key) as response:
            return dict(response.headers)

    def copy_object(self, source_key, destination_key, source_etag=None):
        """Copy an object inside this bucket without sending its body through the app."""
        for key in (source_key, destination_key):
            if (not isinstance(key, str) or not key or key.startswith("/")
                    or any(ord(char) < 32 or ord(char) == 127 for char in key)):
                raise ValueError("OSS 对象路径无效")
        if source_key == destination_key:
            raise ValueError("OSS 复制的源和目标不能相同")
        headers = {
            "x-oss-copy-source": "/" + self.config["bucket"] + "/" + quote(source_key, safe=""),
            "x-oss-object-acl": "private",
            "x-oss-forbid-overwrite": "true",
        }
        if source_etag is not None:
            etag = source_etag.strip().strip('"') if isinstance(source_etag, str) else ""
            if not etag or any(ord(char) < 32 or ord(char) == 127 for char in etag):
                raise ValueError("OSS 源对象 ETag 无效")
            headers["x-oss-copy-source-if-match"] = etag
        with self.request("PUT", destination_key, headers=headers) as response:
            result = ET.fromstring(response.read(65536))
            if result.tag.rsplit("}", 1)[-1] != "CopyObjectResult":
                raise ValueError("OSS 复制对象失败")
            return dict(response.headers)

    def sha256(self, key, chunk_size=1024 * 1024):
        """Return (digest, byte count), reading at most one chunk into memory."""
        if not isinstance(chunk_size, int) or not 0 < chunk_size <= 8 * 1024 * 1024:
            raise ValueError("OSS 读取分块大小无效")
        digest = hashlib.sha256()
        size = 0
        with self.request("GET", key) as response:
            while chunk := response.read(chunk_size):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def download_to(self, key, destination, max_bytes, chunk_size=1024 * 1024):
        """Stream a private object to a temporary file and hash it with a hard cap."""
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("OSS 读取上限无效")
        digest = hashlib.sha256()
        count = 0
        with self.request("GET", key) as response, open(destination, "wb") as output:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    raise ValueError("PDF 文件超过 20 MB 限制")
                digest.update(chunk)
                output.write(chunk)
        return digest.hexdigest(), count

    def sample(self, key):
        with self.request("GET", key, headers={"Range": "bytes=0-4095"}) as response:
            return response.read(4096)

    def verify_private(self, key):
        with self.request("GET", key, {"acl": ""}) as response:
            root = ET.fromstring(response.read(65536))
        if root.findtext(".//Grant") != "private":
            raise StorageSecurityError("OSS 对象未设置为私有，文件尚未登记")
        # A public bucket policy can override the intended protection. Fail closed.
        url = self.config["endpoint"].rstrip("/") + "/" + quote(key, safe="/~")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-0"}), timeout=15):
                raise StorageSecurityError("OSS 对象允许匿名访问，已拒绝登记，请检查 Bucket Policy")
        except HTTPError as exc:
            if exc.code != 403:
                raise

    def delete(self, key):
        with self.request("DELETE", key):
            pass

    def abort(self, key, upload_id):
        with self.request("DELETE", key, {"uploadId": upload_id}):
            pass

    def access_url(self, key, filename, mime, download=False):
        disposition = ("attachment" if download else "inline") + "; filename=download; filename*=UTF-8''" + quote(filename, safe="")
        return self.signed("GET", key, {"response-content-disposition": disposition,
            "response-cache-control": "private, no-store"})
