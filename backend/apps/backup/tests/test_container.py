"""加密外殼:正確的憑證解得開;憑證錯、被改、被截斷、接錯檔都解不開。"""
import os
import tempfile

from django.test import SimpleTestCase

from apps.backup import container
from apps.backup.container import ContainerError


class ContainerTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.secret = os.urandom(20)

    def _path(self, name):
        return os.path.join(self.dir.name, name)

    def _make(self, data, chunk=1024):
        src, enc = self._path("plain"), self._path("enc")
        with open(src, "wb") as f:
            f.write(data)
        digest = container.encrypt_file(src, enc, self.secret, chunk_size=chunk)
        self.assertEqual(digest, container.sha256_file(enc))
        return enc

    def _open(self, enc, secret=None, **kw):
        out = self._path("out")
        container.decrypt_file(enc, out, secret or self.secret, **kw)
        with open(out, "rb") as f:
            return f.read()

    def test_roundtrip_various_sizes(self):
        for size in (0, 1, 1023, 1024, 1025, 4096, 5000):
            data = os.urandom(size)
            self.assertEqual(self._open(self._make(data)), data, size)

    def test_content_is_not_readable_without_key(self):
        enc = self._make(b"member phone 0912345678 " * 200)
        with open(enc, "rb") as f:
            self.assertNotIn(b"0912345678", f.read())

    def test_wrong_key(self):
        enc = self._make(os.urandom(3000))
        with self.assertRaisesMessage(ContainerError, "復原憑證不正確"):
            self._open(enc, secret=os.urandom(20))
        self.assertFalse(os.path.exists(self._path("out")))   # 不留半份

    def test_any_flipped_byte_is_detected(self):
        enc = self._make(os.urandom(3000))
        raw = bytearray(open(enc, "rb").read())
        for pos in (len(container.MAGIC) + 10, len(raw) // 2, len(raw) - 1):
            bad = bytearray(raw)
            bad[pos] ^= 0x01
            with open(enc, "wb") as f:
                f.write(bad)
            with self.assertRaises(ContainerError, msg=pos):
                self._open(enc)

    def test_truncation_is_detected(self):
        enc = self._make(os.urandom(5000))
        raw = open(enc, "rb").read()
        # 砍掉最後一塊(留下的每一塊本身都是完整、驗證得過的)
        header_end = raw.index(b"}") + 1
        first_len = int.from_bytes(raw[header_end:header_end + 4], "big")
        cut = header_end + 4 + first_len
        with open(enc, "wb") as f:
            f.write(raw[:cut])
        with self.assertRaisesMessage(ContainerError, "不完整"):
            self._open(enc)
        with open(enc, "wb") as f:
            f.write(raw[:-7])
        with self.assertRaises(ContainerError):
            self._open(enc)

    def test_reordered_chunks_are_detected(self):
        enc = self._make(os.urandom(3000))
        raw = open(enc, "rb").read()
        header_end = raw.index(b"}") + 1
        n = int.from_bytes(raw[header_end:header_end + 4], "big")
        a = raw[header_end:header_end + 4 + n]
        rest = raw[header_end + 4 + n:]
        n2 = int.from_bytes(rest[:4], "big")
        b, tail = rest[:4 + n2], rest[4 + n2:]
        with open(enc, "wb") as f:
            f.write(raw[:header_end] + b + a + tail)
        with self.assertRaises(ContainerError):
            self._open(enc)

    def test_trailing_garbage_is_detected(self):
        enc = self._make(os.urandom(100))
        with open(enc, "ab") as f:
            f.write(b"\x00\x00\x00\x10" + os.urandom(16))
        with self.assertRaises(ContainerError):
            self._open(enc)

    def test_not_a_backup_file(self):
        junk = self._path("junk")
        with open(junk, "wb") as f:
            f.write(b"PK\x03\x04 this is a zip, not ours")
        with self.assertRaisesMessage(ContainerError, "不是 MP POS 的備份檔"):
            self._open(junk)

    def test_unsupported_version(self):
        enc = self._make(b"x")
        raw = open(enc, "rb").read().replace(b'"container":1', b'"container":9')
        with open(enc, "wb") as f:
            f.write(raw)
        with self.assertRaisesMessage(ContainerError, "不支援這個備份檔版本"):
            self._open(enc)

    def test_size_limit(self):
        enc = self._make(os.urandom(5000))
        with self.assertRaisesMessage(ContainerError, "超過允許的大小"):
            self._open(enc, max_bytes=2000)


class KeyFormatTests(SimpleTestCase):
    def test_roundtrip_and_tolerant_input(self):
        from apps.backup import keys

        secret = os.urandom(20)
        text = keys.format_secret(secret)
        self.assertRegex(text, r"^MP(-[0-9A-HJKMNP-TV-Z]{4}){8}$")
        self.assertEqual(keys.parse_secret(text), secret)
        self.assertEqual(keys.parse_secret(text.lower().replace("-", " ")), secret)
        with self.assertRaises(keys.KeyError_):
            keys.parse_secret(text[:-1])
        with self.assertRaises(keys.KeyError_):
            keys.parse_secret("")
