"""把輸入(自然語言 / 進貨單文字)轉成固定格式的 Intent dict。

兩種 parser:
- DeterministicParser:純規則,不需 LLM、不需網路。給離線測試與最保守模式用,
  也當 LLM 不可用時的後備。輸入是半結構化的進貨單文字。
- LLMParser:呼叫大模型,把任意自然語言轉成同一份 Intent JSON。預設關閉
  (settings.ASSISTANT_LLM_ENABLED=false),需設定金鑰才啟用;永遠不在測試中被呼叫。

無論哪一種,輸出都是同一份 Intent,後面的 resolve / confirm 完全共用。
"""
import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings

from . import intents


class ParseError(Exception):
    """無法解析輸入。"""


class ParserNotConfigured(Exception):
    """LLM parser 未設定(缺金鑰等)。"""


# ── 進貨單文字格式(DeterministicParser)──────────────────────────
# 標頭:  #進貨 供應商=大盤商A 倉庫=門市 課稅=應稅內含
# 明細行:iPhone 15 Pro 256GB 黑 x2 @35000 序號=356...01,356...02
#        保護貼 x10 @50
_HEADER_KEYS = {
    "供應商": "supplier_query", "supplier": "supplier_query",
    "倉庫": "warehouse_query", "倉": "warehouse_query", "warehouse": "warehouse_query",
    "課稅": "tax_method", "tax": "tax_method",
}
_TAX_LABELS = {
    "應稅內含": "taxable_included", "內含": "taxable_included",
    "應稅外加": "taxable_excluded", "外加": "taxable_excluded",
    "未稅": "untaxed",
}
_KV_RE = re.compile(r"(供應商|supplier|倉庫|倉|warehouse|課稅|tax)\s*[=:：]\s*(\S+)", re.I)
_QTY_RE = re.compile(r"[x×*ｘ]\s*(\d+)", re.I)          # x2 / ×2 / *2
_PRICE_RE = re.compile(r"[@＄$]\s*(\d+(?:\.\d+)?)")           # @35000 / $35000
_SERIAL_RE = re.compile(r"(?:序號|imei|sn)\s*[=:：]\s*([0-9A-Za-z,\s、]+)", re.I)


class DeterministicParser:
    def parse(self, raw_input: str, source: str = "purchase_doc") -> dict:
        lines = [ln.strip() for ln in (raw_input or "").splitlines() if ln.strip()]
        if not lines:
            raise ParseError("輸入是空的")

        intent = {"action": intents.CREATE_PURCHASE_ORDER, "tax_method": "taxable_included",
                  "supplier_query": "", "warehouse_query": "", "items": []}

        item_lines = []
        for ln in lines:
            if _KV_RE.search(ln):
                for key, val in _KV_RE.findall(ln):
                    field = _HEADER_KEYS.get(key.lower(), _HEADER_KEYS.get(key))
                    if field == "tax_method":
                        intent["tax_method"] = _TAX_LABELS.get(val, "taxable_included")
                    elif field:
                        intent[field] = val
                # 標頭行若還帶了商品(少見)就不當明細,單純略過殘餘
                continue
            item_lines.append(ln)

        for ln in item_lines:
            item = self._parse_item_line(ln)
            if item:
                intent["items"].append(item)

        if not intent["supplier_query"]:
            raise ParseError("找不到供應商;請在標頭寫「供應商=...」")
        if not intent["items"]:
            raise ParseError("找不到任何進貨明細")
        return intent

    def _parse_item_line(self, ln: str):
        qty_m = _QTY_RE.search(ln)
        price_m = _PRICE_RE.search(ln)
        serial_m = _SERIAL_RE.search(ln)

        serials = []
        if serial_m:
            serials = [s for s in re.split(r"[,\s、]+", serial_m.group(1).strip()) if s]

        # 商品名稱 = 去掉數量/單價/序號標記後的前段
        name = ln
        for m in (qty_m, price_m, serial_m):
            if m:
                name = name[: m.start()] if m.start() < len(name) else name
        name = name.strip(" -•\t")
        if not name:
            return None

        qty = int(qty_m.group(1)) if qty_m else 1
        try:
            unit_price = Decimal(price_m.group(1)) if price_m else Decimal("0")
        except InvalidOperation:
            unit_price = Decimal("0")

        return {
            "product_query": name,
            "qty": qty,
            "unit_price": str(unit_price),
            "serial_numbers": serials,
        }


class LLMParser:
    """把自然語言交給大模型,要求只回傳符合 intents schema 的 JSON。

    預設關閉。啟用需在環境變數設定:
        ASSISTANT_LLM_ENABLED=true
        ASSISTANT_LLM_API_KEY=sk-...
    provider / model 也可從 settings 覆寫。這裡用 stdlib urllib 打 HTTP,
    不新增任何相依套件;實際 provider 的 request/response 形狀請依你選的服務調整。
    """

    SYSTEM_PROMPT = (
        "你是通訊行 POS 的指令解析器。把使用者的話轉成一個 JSON 物件,"
        "只能是以下固定動作之一,且只輸出 JSON、不要多餘文字。\n"
        "動作 schema(create_purchase_order):\n{schema}\n"
        "規則:數量、單價一律數字;序號商品的 serial_numbers 數量要等於 qty;"
        "沒把握的欄位留空字串,不要編造。"
    )

    def __init__(self):
        if not getattr(settings, "ASSISTANT_LLM_ENABLED", False):
            raise ParserNotConfigured("ASSISTANT_LLM_ENABLED 未開啟")
        self.api_key = getattr(settings, "ASSISTANT_LLM_API_KEY", "")
        if not self.api_key:
            raise ParserNotConfigured("缺少 ASSISTANT_LLM_API_KEY")
        self.model = getattr(settings, "ASSISTANT_LLM_MODEL", "claude-sonnet-4-6")
        self.provider = getattr(settings, "ASSISTANT_LLM_PROVIDER", "anthropic")

    def parse(self, raw_input: str, source: str = "nl_text") -> dict:
        text = self._complete(raw_input)
        try:
            data = json.loads(_extract_json(text))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ParseError(f"模型回傳非 JSON:{exc}")
        if data.get("action") not in intents.ALL_ACTIONS:
            raise ParseError(f"未知動作:{data.get('action')}")
        return data

    def _complete(self, user_text: str) -> str:  # pragma: no cover - 需外部服務
        import urllib.request

        system = self.SYSTEM_PROMPT.format(
            schema=json.dumps(intents.CREATE_PURCHASE_ORDER_SCHEMA, ensure_ascii=False)
        )
        # Anthropic Messages API 形狀;換 provider 時改這段即可。
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user_text}],
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["content"][0]["text"]


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else text


def get_parser(prefer_llm: bool = True):
    """依設定回傳可用的 parser;LLM 沒開就退回 DeterministicParser。"""
    if prefer_llm and getattr(settings, "ASSISTANT_LLM_ENABLED", False):
        try:
            return LLMParser()
        except ParserNotConfigured:
            pass
    return DeterministicParser()
