"""Private OSS adapter; credentials stay on the server, legacy config stays valid."""
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
