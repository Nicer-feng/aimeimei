"""Private OSS snapshots keep the app out of the file data path."""
import hashlib
from io import BytesIO
import unittest
from unittest.mock import patch

from infrastructure.storage import PrivateOSS


CONFIG = {
    "configured": True,
    "endpoint": "https://example.oss-cn-hangzhou.aliyuncs.com",
    "region": "cn-hangzhou",
    "bucket": "example",
    "access_key_id": "test-id",
    "access_key_secret": "test-secret",
}


class OSSResponse(BytesIO):
    headers = {"x-oss-request-id": "example-request"}


class PrivateOSSSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.oss = PrivateOSS(CONFIG)

    def test_copy_uses_private_conditional_server_side_request(self):
        response = OSSResponse(b"<CopyObjectResult><ETag>abc</ETag></CopyObjectResult>")
        with patch.object(self.oss, "request", return_value=response) as request:
            headers = self.oss.copy_object("share/one/测试.docx", "share/drafts/new.docx", '"ABCDEF"')
        request.assert_called_once_with("PUT", "share/drafts/new.docx", headers={
            "x-oss-copy-source": "/example/share%2Fone%2F%E6%B5%8B%E8%AF%95.docx",
            "x-oss-object-acl": "private",
            "x-oss-forbid-overwrite": "true",
            "x-oss-copy-source-if-match": "ABCDEF",
        })
        self.assertEqual(headers["x-oss-request-id"], "example-request")

    def test_copy_rejects_self_copy_and_invalid_etag(self):
        with patch.object(self.oss, "request") as request:
            with self.assertRaises(ValueError):
                self.oss.copy_object("share/one", "share/one")
            with self.assertRaises(ValueError):
                self.oss.copy_object("share/one", "share/two", "abc\r\nInjected: yes")
            request.assert_not_called()

    def test_hash_reads_in_bounded_chunks(self):
        data = b"a" * (1024 * 1024 + 53)
        source = OSSResponse(data)
        reads = []
        original_read = source.read

        def read(size):
            reads.append(size)
            return original_read(size)

        with patch.object(source, "read", side_effect=read), patch.object(self.oss, "request", return_value=source) as request:
            self.assertEqual(self.oss.sha256("share/versions/new.docx"), (hashlib.sha256(data).hexdigest(), len(data)))
        request.assert_called_once_with("GET", "share/versions/new.docx")
        self.assertTrue(all(size == 1024 * 1024 for size in reads))
        self.assertGreater(len(reads), 1)


if __name__ == "__main__":
    unittest.main()
