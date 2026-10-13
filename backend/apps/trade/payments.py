"""收款(紅隊 2026-10-14 第 3 條;owner 定:記一筆收到的金額、由舊到新銷單、看得到還欠多少)。**錢不經過平台**,這只是記錄。

「哪一筆錢銷掉哪一張單」不存:每次看的時候把這個同行收到的錢加起來,由舊到新分給他出過貨的單(`ledger`)。
所以出貨取消、整張銷退之後,欠多少自己就對了,不用誰去改收款紀錄。

一張單欠多少 = 它每一次出貨的 貨款 + 運費(取消的出貨、整張銷退掉的出貨不算)。還沒出貨的不算欠。
"""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef

from apps.sales.models import SalesReturn

from . import orders
from .base import ZERO, TradeError
from .models import TradeOrder, TradePartner, TradePayment, TradeShipment

MAX_AMOUNT = 99_999_999


def live_shipments(queryset=None):
    """算數的出貨:沒有取消、它的銷貨單沒有被整張銷退。"""
    queryset = TradeShipment.objects.all() if queryset is None else queryset
    returned = SalesReturn.objects.filter(original_so_id=OuterRef("sales_order_id"), is_void=False)
    return queryset.filter(is_void=False).annotate(returned=Exists(returned)).filter(returned=False)


def status_text(owed: Decimal, paid: Decimal) -> str:
    if owed <= 0:
        return ""
    if paid >= owed:
        return "已收款"
    return "收了一部分" if paid > 0 else "未收款"


def ledger(partner: TradePartner) -> dict:
    """這個同行的帳:每一張出過貨的單欠多少、收了多少(由舊到新分)、合計還欠多少、多收多少。"""
    owed = {}
    for row in live_shipments(TradeShipment.objects.filter(order__partner=partner)).values("order_id", "goods_amount", "shipping_fee"):
        owed[row["order_id"]] = owed.get(row["order_id"], ZERO) + row["goods_amount"] + row["shipping_fee"]
    pool = sum((p.amount for p in TradePayment.objects.filter(partner=partner, is_void=False)), ZERO)
    received = pool
    rows = []
    for order in TradeOrder.objects.filter(pk__in=owed).order_by("id"):
        amount = owed[order.id]
        paid = min(pool, amount)
        pool -= paid
        rows.append({"order": order, "owed": amount, "paid": paid, "due": amount - paid})
    return {
        "orders": rows, "owed": sum((r["owed"] for r in rows), ZERO), "received": received,
        "due": sum((r["due"] for r in rows), ZERO), "credit": pool,
    }


def record(*, tenant, user, partner, amount, request_key, received_on=None, method="", note=""):
    """記一筆收到的錢。回 (那一筆, 是不是這一次新記的)。同一把鑰匙再來回同一筆。"""
    if not isinstance(request_key, str) or not orders.BUYER_KEY.match(request_key) or len(request_key) > 50:
        raise TradeError("這一筆收款的編號不對,請重新整理頁面再試")
    if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= MAX_AMOUNT:
        raise TradeError(f"收到的金額要是 1 到 {MAX_AMOUNT} 的整數")
    if received_on is not None and not isinstance(received_on, date):
        raise TradeError("收款日期不對")
    if partner.tenant_id != tenant.id:
        raise TradeError("找不到這個同行")
    found = TradePayment.objects.filter(tenant=tenant, request_key=request_key).first()
    if found is None:
        try:
            with transaction.atomic():
                return TradePayment.objects.create(
                    tenant=tenant, partner=partner, amount=Decimal(amount), received_on=received_on or date.today(),
                    method=orders._text(method, 20), note=orders._text(note, 200), request_key=request_key,
                    created_by=user if getattr(user, "is_authenticated", False) else None), True
        except IntegrityError:
            found = TradePayment.objects.get(tenant=tenant, request_key=request_key)
    if found.partner_id != partner.id:
        raise TradeError("這把鑰匙是另一個同行的收款")
    return found, False


def void(payment: TradePayment) -> TradePayment:
    """記錯的那一筆作廢(不刪,留著看得到)。"""
    if payment.is_void:
        raise TradeError("這一筆已經作廢了")
    payment.is_void = True
    payment.save(update_fields=["is_void", "updated_at"])
    return payment
