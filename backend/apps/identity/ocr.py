"""進貨單讀圖服務:一張照片 → 固定格式的結構化明細。

準度優先、可切換(對齊 docs/product-roadmap.md 第 2b 步 + 通訊業AI管理助理_API規劃 §12):
- 只負責「把圖讀成明細」,讀完交給 services.run_intake_from_lines → 走既有識別引擎。
- provider 可換:預設 Anthropic 視覺(claude-sonnet-4-6),換 DeepSeek 視覺或別家只改這裡 + settings。
- 預設關閉(OCR_ENABLED=false / 沒金鑰)→ get_ocr_provider() 丟 OcrNotConfigured,
  上傳端點回「尚未設定讀圖模型」,不影響貼文字流程。
- 進貨單無客戶個資,送外部視覺模型是全系統最安全的一段(§21)。

不新增任何相依套件(用 stdlib urllib)。實際 provider 的 request/response 形狀依所選服務調整。
"""
import base64
import json
import re

from django.conf import settings


class OcrNotConfigured(Exception):
    """讀圖模型未設定(未開啟 / 缺金鑰)。"""


class OcrError(Exception):
    """讀圖失敗(模型回傳非預期 / 連線錯誤)。"""


# 要求模型輸出的固定格式;只輸出 JSON。
_SCHEMA_HINT = {
    "supplier_name": "供應商名稱(讀不到留空字串)",
    "doc_no": "出貨單號 / 進貨單號(讀不到留空)",
    "doc_date": "單據日期 YYYY-MM-DD(讀不到留空)",
    "lines": [
        {
            "raw_name": "商品品名(照單據原文,不要自行翻譯或補齊)",
            "supplier_sku": "廠商料號(沒有留空)",
            "barcode": "條碼 / GTIN(沒有留空)",
            "qty": "數量(整數)",
            "unit_cost": "進價單價(數字字串,沒有填 0)",
            "field_confidence": {"raw_name": "0-1", "qty": "0-1", "unit_cost": "0-1"},
        }
    ],
}

_SYSTEM_PROMPT = (
    "你是通訊行進貨單辨識器。看圖片(供應商出貨單 / 進貨單),把每一行商品讀成結構化 JSON。"
    "只輸出一個 JSON 物件,格式如下,不要多餘文字、不要 markdown:\n"
    f"{json.dumps(_SCHEMA_HINT, ensure_ascii=False)}\n"
    "規則:品名照單據原文照抄;數量與單價一律數字;讀不清楚的欄位留空字串並把該欄 "
    "field_confidence 壓低;不要編造不存在的行。"
)


class AnthropicVisionOCR:
    """用 Anthropic 視覺模型讀進貨單。"""

    def __init__(self):
        if not getattr(settings, "OCR_ENABLED", False):
            raise OcrNotConfigured("OCR_ENABLED 未開啟")
        self.api_key = getattr(settings, "OCR_API_KEY", "")
        if not self.api_key:
            raise OcrNotConfigured("缺少 OCR_API_KEY")
        self.model = getattr(settings, "OCR_MODEL", "claude-sonnet-4-6")

    def read(self, image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
        """回傳解析後的結構化明細 dict(含 supplier_name / doc_no / lines)。"""
        text = self._complete(image_bytes, media_type)
        try:
            data = json.loads(_extract_json(text))
        except (ValueError, json.JSONDecodeError) as exc:
            raise OcrError(f"模型回傳非 JSON:{exc}")
        if not isinstance(data, dict) or "lines" not in data:
            raise OcrError("模型回傳缺少 lines")
        return data

    def _complete(self, image_bytes, media_type):  # pragma: no cover - 需外部服務
        import urllib.request

        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "system": _SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": "把這張進貨單的每一行讀成上面規定的 JSON。"},
                ],
            }],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - 對外連線各種錯統一轉 OcrError
            raise OcrError(f"讀圖連線失敗:{exc}")
        return body["content"][0]["text"]


def _extract_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


def get_ocr_provider():
    """依設定回傳讀圖 provider;沒設定就丟 OcrNotConfigured。"""
    provider = getattr(settings, "OCR_PROVIDER", "anthropic")
    if provider == "anthropic":
        return AnthropicVisionOCR()
    # 未來加 deepseek 視覺等,在這裡分支。
    raise OcrNotConfigured(f"不支援的讀圖 provider:{provider}")
