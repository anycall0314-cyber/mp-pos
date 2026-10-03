"""備份檔的加密外殼。

沒有自己設計加密演算法:金鑰由 HKDF-SHA256 導出、內容用 AES-256-GCM(皆出自
`cryptography` 套件)。大檔切成固定大小的區塊逐塊加密,做法是文獻上的 STREAM
(Hoang–Reyhanitabar–Rogaway–Vizár 2015;age、Tink 的串流加密都是這個做法):

- 每個檔案有自己的隨機 salt → 自己的金鑰,所以 nonce 用區塊序號就不會重複。
- nonce = 11 bytes 區塊序號 + 1 byte「是不是最後一塊」。把區塊調換順序、
  從中間截斷、或把別的檔案的區塊接進來,解密都會失敗。
- 開頭的明文檔頭(格式版本、salt、區塊大小)整段當 AAD 綁進每一塊,改檔頭也會失敗。

檔頭只放解密需要的東西。哪一家公司、有哪些門市、幾筆資料 —— 這些都在加密的
內容裡,沒有憑證看不到。

檔案格式:
    8 bytes   魔術字 "MPPOSBK\\x01"
    4 bytes   檔頭長度 N(big-endian)
    N bytes   檔頭 JSON
    重複:    4 bytes 密文長度 + 密文(含 16 bytes 驗證碼)
"""
import hashlib
import json
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"MPPOSBK\x01"
CONTAINER_VERSION = 1
CHUNK_SIZE = 1024 * 1024
_TAG = 16
_MAX_HEADER = 4096
_INFO = b"mppos-company-backup-v1"


class ContainerError(Exception):
    """備份檔打不開:格式不對、版本不支援、憑證不對、或內容被改過 / 不完整。"""


def _derive_key(secret: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=_INFO).derive(secret)


def _nonce(index: int, last: bool) -> bytes:
    return index.to_bytes(11, "big") + (b"\x01" if last else b"\x00")


def encrypt_file(src_path, dst_path, secret: bytes, *, key_fingerprint: str = "",
                 chunk_size: int = CHUNK_SIZE) -> str:
    """把 src 加密寫到 dst,回傳 dst 的 sha256(邊寫邊算,不用再讀一次)。"""
    salt = os.urandom(32)
    header = json.dumps({
        "container": CONTAINER_VERSION,
        "cipher": "aes-256-gcm",
        "kdf": "hkdf-sha256",
        "salt": salt.hex(),
        "chunk_size": chunk_size,
        # 讓人知道這份檔案是用哪一組憑證加密的(換過憑證時用);不能拿來解密
        "key_fingerprint": key_fingerprint,
    }, separators=(",", ":")).encode()
    prefix = MAGIC + struct.pack(">I", len(header)) + header
    aead = AESGCM(_derive_key(secret, salt))
    digest = hashlib.sha256()

    def emit(out, data):
        out.write(data)
        digest.update(data)

    with open(src_path, "rb") as src, open(dst_path, "wb") as out:
        emit(out, prefix)
        index = 0
        block = src.read(chunk_size)
        while True:
            following = src.read(chunk_size)
            last = not following
            sealed = aead.encrypt(_nonce(index, last), block, prefix)
            emit(out, struct.pack(">I", len(sealed)) + sealed)
            if last:
                break
            block = following
            index += 1
        out.flush()
        os.fsync(out.fileno())
    return digest.hexdigest()


def read_header(path) -> dict:
    """只讀明文檔頭(不需要憑證)。格式不對就丟 ContainerError。"""
    with open(path, "rb") as f:
        return _read_header(f)[0]


def _read_header(f):
    magic = f.read(len(MAGIC))
    if magic != MAGIC:
        raise ContainerError("這不是 MP POS 的備份檔")
    raw_len = f.read(4)
    if len(raw_len) != 4:
        raise ContainerError("備份檔不完整")
    (n,) = struct.unpack(">I", raw_len)
    if n > _MAX_HEADER:
        raise ContainerError("備份檔的檔頭異常")
    raw = f.read(n)
    if len(raw) != n:
        raise ContainerError("備份檔不完整")
    try:
        header = json.loads(raw)
    except ValueError:
        raise ContainerError("備份檔的檔頭讀不出來")
    if not isinstance(header, dict) or header.get("container") != CONTAINER_VERSION:
        raise ContainerError(
            f"不支援這個備份檔版本({header.get('container') if isinstance(header, dict) else '?'})"
        )
    if header.get("cipher") != "aes-256-gcm" or header.get("kdf") != "hkdf-sha256":
        raise ContainerError("不支援這個備份檔的加密方式")
    chunk = header.get("chunk_size")
    if not isinstance(chunk, int) or not (1024 <= chunk <= 64 * 1024 * 1024):
        raise ContainerError("備份檔的檔頭異常")
    return header, magic + raw_len + raw


def decrypt_file(src_path, dst_path, secret: bytes, *, max_bytes: int | None = None) -> None:
    """解密 src 寫到 dst。憑證不對、被改過、被截斷都會丟 ContainerError,
    而且**不會留下半份的 dst**。"""
    ok = False
    try:
        with open(src_path, "rb") as f, open(dst_path, "wb") as out:
            header, prefix = _read_header(f)
            try:
                salt = bytes.fromhex(header["salt"])
            except (KeyError, ValueError, TypeError):
                raise ContainerError("備份檔的檔頭異常")
            aead = AESGCM(_derive_key(secret, salt))
            limit = header["chunk_size"] + _TAG
            index, written, finished = 0, 0, False
            while True:
                raw_len = f.read(4)
                if not raw_len:
                    break
                if finished or len(raw_len) != 4:
                    raise ContainerError("備份檔內容不完整或被改過")
                (n,) = struct.unpack(">I", raw_len)
                if n < _TAG or n > limit:
                    raise ContainerError("備份檔內容不完整或被改過")
                sealed = f.read(n)
                if len(sealed) != n:
                    raise ContainerError("備份檔不完整(可能沒有下載完)")
                # 最後一塊的 nonce 帶「結束」記號。先當一般區塊解,不行再當最後一塊。
                # 這樣不必先知道總共幾塊,又能確保檔案是在正確的地方結束。
                block = None
                for last in (False, True):
                    try:
                        block = aead.decrypt(_nonce(index, last), sealed, prefix)
                        finished = last
                        break
                    except InvalidTag:
                        continue
                if block is None:
                    raise ContainerError(
                        "復原憑證不正確,或備份檔已損毀" if index == 0
                        else "備份檔內容不完整或被改過"
                    )
                written += len(block)
                if max_bytes is not None and written > max_bytes:
                    raise ContainerError("備份檔解開後超過允許的大小")
                out.write(block)
                index += 1
            if not finished:
                raise ContainerError("備份檔不完整(可能沒有下載完)")
        ok = True
    finally:
        if not ok:
            try:
                os.remove(dst_path)
            except OSError:
                pass


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
