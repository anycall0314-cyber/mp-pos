"""把上傳的照片整理成「大圖 + 縮圖」兩個 JPEG。

伺服器自己打開圖片來確認真的是圖(副檔名與瀏覽器講的類型都不算數),轉正(手機直拍的方向寫在 EXIF 裡)、
去掉透明、縮到上限以內再存。HEIC / HEIF(iPhone 的原生格式)有裝 pillow-heif 就讀得懂。
"""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # iPhone 的 HEIC / HEIF
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover - 沒裝也能跑,只是讀不了 HEIC
    HEIF_OK = False

MAX_BYTES = 20 * 1024 * 1024      # 單檔原始上限
MAX_PIXELS = 64_000_000           # 再大的圖不解(避免一張圖吃光記憶體;手機 4800 萬 / 5000 萬畫素的原圖收得下)
FULL_EDGE = 2400                  # 大圖長邊:接口、標籤上的小字還看得清楚
THUMB_EDGE = 480                  # 縮圖長邊:清單與照片格
ALLOWED = {"JPEG", "MPO", "PNG", "WEBP", "HEIF", "HEIC"}

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class PhotoError(Exception):
    """這張照片收不下來(原因會顯示給使用者)。"""


def _jpeg(img, edge, quality) -> bytes:
    """把 img **就地**縮到長邊 edge 以內再存成 JPEG(不另外複製一份:原圖可能有幾千萬畫素)。"""
    img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def process(upload) -> tuple[bytes, bytes, int, int]:
    """回 (大圖, 縮圖, 寬, 高)。upload 是上傳的檔案物件。"""
    data = upload.read(MAX_BYTES + 1)
    if not data:
        raise PhotoError("沒有收到照片")
    if len(data) > MAX_BYTES:
        raise PhotoError("照片太大(上限 20MB)")
    try:
        img = Image.open(BytesIO(data))
        fmt = (img.format or "").upper()
        if fmt not in ALLOWED:
            raise PhotoError("這種檔案不是照片(請用 JPG / PNG / WebP / HEIC)")
        if img.width * img.height > MAX_PIXELS:
            raise PhotoError("照片尺寸太大")
        # JPEG 可以解碼時就先縮(不用整張原尺寸攤開在記憶體裡);留兩倍的餘裕再細縮
        img.draft("RGB", (FULL_EDGE * 2, FULL_EDGE * 2))
        img.load()
        if img.mode == "P":
            img = img.convert("RGBA")  # 調色盤圖不能直接好好縮
        # 先縮到大圖的尺寸再轉正、鋪底:這幾步都會另外複製一份,原圖有幾千萬畫素時不能整張拿去做
        img.thumbnail((FULL_EDGE, FULL_EDGE), Image.Resampling.LANCZOS)
        img = ImageOps.exif_transpose(img)
        # 用「某一個顏色當透明」的 PNG(不是 RGBA):也要當成有透明的來鋪白底,不然那一塊轉成 JPEG 會變黑
        if img.info.get("transparency") is not None and img.mode not in ("RGBA", "LA"):
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA", "P"):
            # 透明的地方鋪白底(JPEG 沒有透明)
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[-1])
            img = flat
        elif img.mode != "RGB":
            img = img.convert("RGB")
    except PhotoError:
        raise
    except UnidentifiedImageError:
        raise PhotoError(
            "這個檔案打不開,不是照片" if HEIF_OK else "這個檔案打不開(HEIC 請先轉成 JPG)"
        )
    except Image.DecompressionBombError:
        raise PhotoError("照片尺寸太大")
    except Exception:
        raise PhotoError("照片打不開,可能已經損壞")
    # 先縮成大圖(就地),記下實際存下來多大;縮圖再從大圖往下縮
    full = _jpeg(img, FULL_EDGE, 86)
    w, h = img.size
    thumb = _jpeg(img, THUMB_EDGE, 80)
    return full, thumb, w, h
