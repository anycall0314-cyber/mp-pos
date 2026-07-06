"""固定動作集合(Intent registry)。

核心原則:LLM / parser 只能輸出「這裡列出的有限動作」,不是自由文字。
每個動作對應一個既有的帳本 service。新增動作 = 在這裡加一筆 + 在 services.EXECUTORS
掛一個 executor,其餘(解析、確認、audit)共用同一條管線。

目前只實作 create_purchase_order;其餘為保留位,體現「先把一條做到滴水不漏,
再往外加」的節奏。
"""

CREATE_PURCHASE_ORDER = "create_purchase_order"

# 已實作的動作
IMPLEMENTED_ACTIONS = {CREATE_PURCHASE_ORDER}

# 保留(規劃中)的動作:先宣告固定集合,尚未接 executor
RESERVED_ACTIONS = {
    "create_sales_order",   # 銷貨:接 sales.services.commit_sales_order
    "create_transfer",      # 調撥:接 transfers.services
    "update_serial_status", # IMEI 狀態維護:接 inventory
    "query_stock",          # 查庫存(唯讀,不寫帳)
}

ALL_ACTIONS = IMPLEMENTED_ACTIONS | RESERVED_ACTIONS


# 給 LLM 的 JSON 輸出規格(create_purchase_order)。
# LLMParser 會把這段塞進 system prompt,要求模型「只輸出符合此 schema 的 JSON」。
CREATE_PURCHASE_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"const": CREATE_PURCHASE_ORDER},
        "supplier_query": {"type": "string", "description": "供應商名稱或代碼(自然語言即可)"},
        "warehouse_query": {"type": "string", "description": "入庫倉/門市名稱或代碼;沒提可留空"},
        "tax_method": {
            "type": "string",
            "enum": ["taxable_included", "taxable_excluded", "untaxed"],
            "description": "課稅別;沒提預設 taxable_included(應稅內含)",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_query": {"type": "string", "description": "商品名稱/型號/SKU/條碼"},
                    "qty": {"type": "integer", "minimum": 1},
                    "unit_price": {"type": "number", "minimum": 0},
                    "serial_numbers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "逐台 IMEI/SN;序號商品數量需等於 qty,配件留空",
                    },
                },
                "required": ["product_query", "qty", "unit_price"],
            },
        },
    },
    "required": ["action", "supplier_query", "items"],
}

SCHEMA_BY_ACTION = {CREATE_PURCHASE_ORDER: CREATE_PURCHASE_ORDER_SCHEMA}
