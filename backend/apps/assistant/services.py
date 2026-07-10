"""AI 指令管線的業務層。

兩個進入點:
    interpret(tenant, raw_input, ...)  → 解析 + 對應主檔 → 產出「提案」或「追問」
    confirm(command_log, user)         → 使用者確認後,呼叫既有帳本 service 真正過帳

鐵律:
1. interpret 階段**不寫任何帳本資料**,只讀主檔、產出提案。
2. 所有真正的寫入都在 confirm 階段,且一律走既有 service(commit_purchase_order),
   讓既有的驗證(序號數=數量、序號不重複…)當防呆網——LLM 解析錯也進不了 DB。
3. 每一步都落在 CommandLog 上,可回溯。
"""
from decimal import Decimal

from django.db import transaction
from rest_framework import serializers as drf_serializers

from apps.purchasing.serializers import PurchaseOrderSerializer
from apps.purchasing.services import PurchaseOrderError, commit_purchase_order

from . import intents
from .models import CommandLog
from .parsers import ParseError, get_parser
from .resolvers import resolve_product, resolve_supplier, resolve_warehouse


# ─────────────────────────── interpret ───────────────────────────
def interpret(tenant, raw_input, source=CommandLog.Source.NL_TEXT, user=None, parser=None):
    """解析輸入並建立一筆 CommandLog(狀態:待確認 / 待釐清 / 失敗)。"""
    parser = parser or get_parser()
    cmd = CommandLog(tenant=tenant, source=source, raw_input=raw_input, created_by=user)

    try:
        intent = parser.parse(raw_input, source=source)
    except ParseError as exc:
        cmd.status = CommandLog.Status.FAILED
        cmd.message = f"無法解析:{exc}"
        cmd.save()
        return cmd

    cmd.parsed_intent = intent
    cmd.intent_action = intent.get("action", "")

    if cmd.intent_action not in intents.IMPLEMENTED_ACTIONS:
        cmd.status = CommandLog.Status.FAILED
        cmd.message = f"目前尚未支援的動作:{cmd.intent_action or '(未知)'}"
        cmd.save()
        return cmd

    builder = _PROPOSAL_BUILDERS[cmd.intent_action]
    proposal, clarifications = builder(tenant, intent)

    if clarifications:
        cmd.clarification = clarifications
        cmd.status = CommandLog.Status.NEEDS_CLARIFICATION
        cmd.message = "有項目需要你確認"
    else:
        cmd.proposal = proposal
        cmd.status = CommandLog.Status.AWAITING_CONFIRM
        cmd.message = "已備妥提案,請確認後過帳"
    cmd.save()
    return cmd


def _candidate_brief(objs):
    out = []
    for o in objs[:6]:
        out.append({
            "id": o.id,
            "label": str(o),
            "sku": getattr(o, "sku", ""),
            "name": getattr(o, "name", ""),
        })
    return out


def _build_purchase_order_proposal(tenant, intent):
    """把 create_purchase_order 的 Intent 解析成可執行 payload;不確定就回追問。"""
    clarifications = []

    sup = resolve_supplier(tenant, intent.get("supplier_query", ""))
    if sup.status != "resolved":
        clarifications.append({
            "field": "supplier",
            "query": intent.get("supplier_query", ""),
            "reason": sup.status,
            "message": _msg("供應商", intent.get("supplier_query", ""), sup.status),
            "candidates": _candidate_brief(sup.candidates),
        })

    wh = resolve_warehouse(tenant, intent.get("warehouse_query", ""))
    if wh.status != "resolved":
        clarifications.append({
            "field": "warehouse",
            "query": intent.get("warehouse_query", ""),
            "reason": wh.status,
            "message": _msg("倉庫", intent.get("warehouse_query", ""), wh.status),
            "candidates": _candidate_brief(wh.candidates),
        })

    payload_items, display_items = [], []
    for idx, raw_item in enumerate(intent.get("items", [])):
        pr = resolve_product(tenant, raw_item.get("product_query", ""))
        qty = int(raw_item.get("qty", 1))
        unit_price = str(raw_item.get("unit_price", "0"))
        serials = list(raw_item.get("serial_numbers", []) or [])
        if pr.status != "resolved":
            clarifications.append({
                "field": f"items[{idx}].product",
                "query": raw_item.get("product_query", ""),
                "reason": pr.status,
                "message": _msg("商品", raw_item.get("product_query", ""), pr.status),
                "candidates": _candidate_brief(pr.candidates),
            })
            continue
        product = pr.obj
        payload_items.append({
            "product": product.id,
            "qty": qty,
            "unit_price": unit_price,
            "serial_numbers": serials,
        })
        display_items.append({
            "sku": product.sku,
            "name": product.name,
            "qty": qty,
            "unit_price": unit_price,
            "requires_serial": product.requires_serial,
            "serial_count": len(serials),
            "line_total": str((Decimal(unit_price) * qty)),
            # 前端可據此提醒:序號商品但序號數不符
            "serial_mismatch": bool(product.requires_serial and len(serials) != qty),
        })

    if clarifications:
        return {}, clarifications

    payload = {
        "supplier": sup.obj.id,
        "warehouse": wh.obj.id,
        "tax_method": intent.get("tax_method", "taxable_included"),
        "items": payload_items,
    }
    total_preview = sum((Decimal(i["unit_price"]) * i["qty"] for i in payload_items), Decimal("0"))
    display = {
        "action_label": "進貨單",
        "supplier": {"id": sup.obj.id, "label": str(sup.obj)},
        "warehouse": {"id": wh.obj.id, "label": str(wh.obj)},
        "tax_method": payload["tax_method"],
        "items": display_items,
        "total_preview": str(total_preview),
    }
    return {"payload": payload, "display": display}, []


def _msg(kind, query, status):
    if status == "ambiguous":
        return f"「{query}」對應到多個{kind},請選一個"
    return f"找不到{kind}「{query}」,請確認或先建檔"


_PROPOSAL_BUILDERS = {
    intents.CREATE_PURCHASE_ORDER: _build_purchase_order_proposal,
}


# ─────────────────────────── confirm ───────────────────────────
def confirm(cmd: CommandLog, user=None) -> CommandLog:
    """使用者確認提案後,真正過帳。只有 AWAITING_CONFIRM 能確認。"""
    from django.conf import settings

    # P0 契約:預設關閉助理直接建進貨單的寫入旁路,一律改走待確認入庫(Intake)。
    if not getattr(settings, "ASSISTANT_DIRECT_COMMIT_ENABLED", False):
        raise CommandError("助理直接過帳已停用,請改用『待確認入庫』流程")
    if cmd.status != CommandLog.Status.AWAITING_CONFIRM:
        raise CommandError(f"此指令狀態為「{cmd.get_status_display()}」,不能確認")

    executor = _EXECUTORS.get(cmd.intent_action)
    if executor is None:
        raise CommandError(f"沒有對應的執行器:{cmd.intent_action}")

    try:
        doc_type, doc_id, doc_no = executor(cmd, user)
    except (PurchaseOrderError, drf_serializers.ValidationError) as exc:
        cmd.status = CommandLog.Status.FAILED
        cmd.message = f"過帳失敗:{_err_text(exc)}"
        cmd.save(update_fields=["status", "message", "updated_at"])
        return cmd

    cmd.status = CommandLog.Status.COMMITTED
    cmd.result_doc_type = doc_type
    cmd.result_doc_id = doc_id
    cmd.confirmed_by = user
    cmd.message = f"已建立{doc_no}"
    cmd.save(update_fields=[
        "status", "result_doc_type", "result_doc_id", "confirmed_by", "message", "updated_at"
    ])
    return cmd


def _execute_create_purchase_order(cmd: CommandLog, user):
    """重用既有進貨單序列化器 + 過帳 service,與 ViewSet.perform_create 完全一致。"""
    payload = (cmd.proposal or {}).get("payload")
    if not payload:
        raise CommandError("提案缺少 payload")
    ser = PurchaseOrderSerializer(data=payload)
    ser.is_valid(raise_exception=True)
    with transaction.atomic():
        ser.save(tenant=cmd.tenant, created_by=user)
        commit_purchase_order(ser.instance)
    return "purchase_order", ser.instance.id, ser.instance.no


_EXECUTORS = {
    intents.CREATE_PURCHASE_ORDER: _execute_create_purchase_order,
}


class CommandError(Exception):
    """指令管線錯誤;view 轉成 400。"""


def _err_text(exc) -> str:
    if isinstance(exc, drf_serializers.ValidationError):
        return str(exc.detail)
    return str(exc)
