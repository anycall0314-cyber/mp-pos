"""調撥單兩階段 service。

階段 1:dispatch_transfer_order(來源倉送出)
- 序號商品:serial.status = in_transit、warehouse = None
- 配件:from_warehouse balance.qty -= it.qty;快照當下單台成本到 it.unit_cost_at_dispatch
- 寫 StockMovement TRANSFER_OUT
- status = dispatched

階段 2:confirm_transfer_order(目的倉確認入庫)
- 序號商品:serial.status = in_stock、warehouse = to_warehouse
- 配件:to_warehouse balance.qty += it.qty,依 it.unit_cost_at_dispatch 重算加權平均
- 寫 StockMovement TRANSFER_IN
- status = confirmed

作廢 void_transfer_order(智能回滾)
- 從 dispatched:來源倉恢復(序號回 in_stock、配件 qty 加回)
- 從 confirmed:來源倉恢復、目的倉扣除
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.tenant_fields import same_company
from apps.inventory.locking import lock_document, lock_stock_rows, locked_balance
from apps.inventory.models import ProductSerial, StockBalance, StockMovement

from .models import TransferOrder, TransferOrderItemSerial

CENTS = Decimal("0.01")


class TransferOrderError(Exception):
    """調撥業務錯誤;view 轉成 400。"""


def _check_company(to: TransferOrder, items):
    if not same_company(to.tenant_id, to.from_warehouse, to.to_warehouse):
        raise TransferOrderError("來源 / 目的門市不屬於這家公司")
    for it in items:
        links = list(it.serials.all())
        serials = [s.serial for s in links]
        if not same_company(to.tenant_id, it, it.product, *links, *serials):
            raise TransferOrderError(f"第 {it.line_no} 行的商品 / 序號不屬於這家公司")


def _serial_ids(to: TransferOrder):
    return list(
        TransferOrderItemSerial.objects.filter(item__to=to).values_list("serial_id", flat=True)
    )


def _stock_items(items):
    """走「庫存餘額」的明細(配件:不逐支記)。"""
    return [it for it in items if not it.product.requires_serial and not it.product.is_virtual]


def _validate_dispatch(to: TransferOrder, items):
    if not items:
        raise TransferOrderError("無明細,無法過帳")
    _check_company(to, items)
    if to.from_warehouse_id == to.to_warehouse_id:
        raise TransferOrderError("來源倉與目的倉不可相同")

    seen_serials = set()
    for it in items:
        product = it.product
        if product.is_virtual:
            raise TransferOrderError(
                f"第 {it.line_no} 行虛擬商品 {product.sku} 不可調撥"
            )
        if it.qty <= 0:
            raise TransferOrderError(f"第 {it.line_no} 行數量需 > 0")

        item_serials = list(it.serials.select_related("serial").all())
        if product.requires_serial:
            if len(item_serials) != it.qty:
                raise TransferOrderError(
                    f"第 {it.line_no} 行需 {it.qty} 個序號,目前 {len(item_serials)} 個"
                )
            for sos in item_serials:
                s = sos.serial
                if s.product_id != product.id:
                    raise TransferOrderError(
                        f"第 {it.line_no} 行序號 {s.serial_no} 不屬於商品 {product.sku}"
                    )
                if s.status != ProductSerial.Status.IN_STOCK:
                    raise TransferOrderError(
                        f"第 {it.line_no} 行序號 {s.serial_no} 狀態為「{s.get_status_display()}」,不可調撥"
                    )
                if s.warehouse_id != to.from_warehouse_id:
                    raise TransferOrderError(
                        f"第 {it.line_no} 行序號 {s.serial_no} 不在來源倉"
                    )
                if s.id in seen_serials:
                    raise TransferOrderError(f"序號 {s.serial_no} 重複出現")
                seen_serials.add(s.id)
        else:
            if item_serials:
                raise TransferOrderError(
                    f"第 {it.line_no} 行配件 {product.sku} 不可指定序號"
                )
            bal = StockBalance.objects.filter(
                tenant=to.tenant,
                product=product,
                warehouse=to.from_warehouse,
            ).first()
            current = bal.qty if bal else 0
            if current < it.qty:
                raise TransferOrderError(
                    f"第 {it.line_no} 行 {product.sku} 在 {to.from_warehouse.code} "
                    f"現有 {current},不足調撥 {it.qty}"
                )


def dispatch_transfer_order(to: TransferOrder) -> TransferOrder:
    """來源倉送出。建立時自動呼叫。"""
    items = list(
        to.items.select_related("product")
        .prefetch_related("serials__serial")
        .all()
    )

    with transaction.atomic():
        # 先鎖再檢查、再改(規則見 apps/inventory/locking.py):這張單的序號、來源門市的庫存餘額。
        # 同一支 IMEI 同時被銷貨與調撥選到,只會有一邊成功。
        lock_document(to)
        lock_stock_rows(
            to.tenant, serial_ids=_serial_ids(to),
            balances=[(it.product, to.from_warehouse) for it in _stock_items(items)],
        )
        _validate_dispatch(to, items)
        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    s.status = ProductSerial.Status.IN_TRANSIT
                    s.warehouse = None
                    s.save(update_fields=["status", "warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.TRANSFER_OUT,
                        from_warehouse=to.from_warehouse,
                        to_warehouse=to.to_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 派發 第 {it.line_no} 行",
                    )
            else:
                src = locked_balance(to.tenant, product, to.from_warehouse)
                if src is None or src.qty < it.qty:
                    # 同一個商品在這張單出現好幾行時,前面幾行已經扣掉一部分
                    raise TransferOrderError(
                        f"第 {it.line_no} 行 {product.sku} 在 {to.from_warehouse.code} "
                        f"現有 {src.qty if src else 0},不足調撥 {it.qty}"
                    )
                it.unit_cost_at_dispatch = src.weighted_avg_cost
                it.save(update_fields=["unit_cost_at_dispatch"])
                src.qty -= it.qty
                if src.qty == 0:
                    src.weighted_avg_cost = Decimal("0")
                src.save(update_fields=["qty", "weighted_avg_cost"])
                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.TRANSFER_OUT,
                    from_warehouse=to.from_warehouse,
                    to_warehouse=to.to_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 派發 第 {it.line_no} 行 {product.sku} ×{it.qty}",
                )

        to.status = TransferOrder.Status.DISPATCHED
        to.save(update_fields=["status"])
    return to


def confirm_transfer_order(to: TransferOrder, user=None) -> TransferOrder:
    """目的倉確認入庫。

    鎖住這張調撥單之後才看它是不是還在「派發中」:兩個人同時按確認只會入庫一次。
    """
    with transaction.atomic():
        if lock_document(to) is None:
            raise TransferOrderError("找不到這張調撥單")
        if to.is_void:
            raise TransferOrderError("此單已作廢,無法確認")
        if to.status != TransferOrder.Status.DISPATCHED:
            raise TransferOrderError("此單非派發中狀態,無法確認")

        items = list(
            to.items.select_related("product")
            .prefetch_related("serials__serial")
            .all()
        )
        _check_company(to, items)
        lock_stock_rows(
            to.tenant, serial_ids=_serial_ids(to),
            balances=[(it.product, to.to_warehouse) for it in _stock_items(items)],
            create=True,
        )
        now = timezone.now()
        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    if s.status != ProductSerial.Status.IN_TRANSIT:
                        raise TransferOrderError(
                            f"序號 {s.serial_no} 非調撥中狀態,無法確認"
                        )
                    s.status = ProductSerial.Status.IN_STOCK
                    s.warehouse = to.to_warehouse
                    s.save(update_fields=["status", "warehouse"])
                    StockMovement.objects.create(
                        tenant=to.tenant,
                        serial=s,
                        movement_type=StockMovement.MovementType.TRANSFER_IN,
                        from_warehouse=to.from_warehouse,
                        to_warehouse=to.to_warehouse,
                        ref_doc_type="transfer_order",
                        ref_doc_id=to.id,
                        note=f"調撥單 {to.no} 確認 第 {it.line_no} 行",
                    )
            else:
                dst = locked_balance(to.tenant, product, to.to_warehouse, create=True)
                new_qty = dst.qty + it.qty
                if new_qty > 0:
                    old_value = Decimal(dst.qty) * dst.weighted_avg_cost
                    moved_value = Decimal(it.qty) * it.unit_cost_at_dispatch
                    dst.weighted_avg_cost = (
                        (old_value + moved_value) / Decimal(new_qty)
                    ).quantize(CENTS)
                dst.qty = new_qty
                dst.save(update_fields=["qty", "weighted_avg_cost"])
                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.TRANSFER_IN,
                    from_warehouse=to.from_warehouse,
                    to_warehouse=to.to_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 確認 第 {it.line_no} 行 {product.sku} ×{it.qty}",
                )

        to.status = TransferOrder.Status.CONFIRMED
        to.confirmed_at = now
        to.confirmed_by = user
        to.save(update_fields=["status", "confirmed_at", "confirmed_by"])
    return to


def void_transfer_order(to: TransferOrder) -> TransferOrder:
    """智能回滾。
    - 派發中:序號 in_transit → in_stock 回來源倉;配件 balance 回補來源倉
    - 已完成:序號從目的倉移回來源倉(必須仍 in_stock);配件目的倉扣、來源倉加

    鎖住這張調撥單之後才看它是「派發中」還是「已完成」、是不是已經作廢:
    作廢與確認同時按、或兩個人同時按作廢,都只會照其中一個先後順序做一次。
    """
    with transaction.atomic():
        if lock_document(to) is None:
            raise TransferOrderError("找不到這張調撥單")
        if to.is_void:
            raise TransferOrderError("此單已作廢")

        items = list(
            to.items.select_related("product")
            .prefetch_related("serials__serial")
            .all()
        )
        is_confirmed = to.status == TransferOrder.Status.CONFIRMED
        stock_items = _stock_items(items)
        lock_stock_rows(
            to.tenant, serial_ids=_serial_ids(to),
            balances=[(it.product, to.from_warehouse) for it in stock_items]
            + ([(it.product, to.to_warehouse) for it in stock_items] if is_confirmed else []),
            create=True,
        )

        # 預檢(鎖到之後)
        # 序號商品:不再因序號狀態不符而擋下作廢。
        #   序號若已脫離本單掌控(被其他流程動走,例如又被別張單調走 / 銷貨 / 手動改),
        #   作廢時會「跳過該序號回滾」(不硬搬,避免弄亂已在別處正常使用的序號),
        #   只記一筆 audit。這樣派發中 / 已完成的單都不會變成無法作廢的死鎖單。
        #   配件(非序號)在「已完成」作廢時仍須檢查目的倉數量足夠,否則會變負庫存
        #   (同一個商品在這張單出現好幾行時要加總)。
        if is_confirmed:
            need = {}
            for it in stock_items:
                need[it.product_id] = need.get(it.product_id, 0) + it.qty
            for it in stock_items:
                bal = locked_balance(to.tenant, it.product, to.to_warehouse)
                current = bal.qty if bal else 0
                if current < need[it.product_id]:
                    raise TransferOrderError(
                        f"商品 {it.product.sku} 在目的倉 {to.to_warehouse.code} "
                        f"現有 {current},無法退回本單的 {need[it.product_id]} 件"
                    )

        for it in items:
            product = it.product
            if product.requires_serial:
                for sos in it.serials.select_related("serial").all():
                    s = sos.serial
                    # 判斷這隻序號是否仍由本單掌控:
                    #  - 已完成單:序號要還在目的倉 in_stock,才把它搬回來源倉
                    #  - 派發中單:序號要還在 in_transit,才把它放回來源倉 in_stock
                    # 若序號已被其他流程動走(不符上述),跳過回滾、不動序號,
                    # 只記一筆 audit movement,避免弄亂已在別處正常使用的序號。
                    if is_confirmed:
                        can_rollback = (
                            s.status == ProductSerial.Status.IN_STOCK
                            and s.warehouse_id == to.to_warehouse_id
                        )
                    else:
                        can_rollback = (
                            s.status == ProductSerial.Status.IN_TRANSIT
                        )
                    if can_rollback:
                        s.status = ProductSerial.Status.IN_STOCK
                        s.warehouse = to.from_warehouse
                        s.save(update_fields=["status", "warehouse"])
                        StockMovement.objects.create(
                            tenant=to.tenant,
                            serial=s,
                            movement_type=StockMovement.MovementType.VOID,
                            from_warehouse=to.to_warehouse if is_confirmed else None,
                            to_warehouse=to.from_warehouse,
                            ref_doc_type="transfer_order",
                            ref_doc_id=to.id,
                            note=f"調撥單 {to.no} 作廢({to.get_status_display()})",
                        )
                    else:
                        # 序號已脫離本單掌控,僅記 audit,不改序號狀態 / 倉別
                        StockMovement.objects.create(
                            tenant=to.tenant,
                            serial=s,
                            movement_type=StockMovement.MovementType.VOID,
                            from_warehouse=None,
                            to_warehouse=None,
                            ref_doc_type="transfer_order",
                            ref_doc_id=to.id,
                            note=(
                                f"調撥單 {to.no} 作廢({to.get_status_display()});"
                                f"序號 {s.serial_no} 當下為「{s.get_status_display()}」"
                                f"已脫離本單,跳過回滾"
                            ),
                        )
            else:
                if is_confirmed:
                    dst = locked_balance(to.tenant, product, to.to_warehouse)
                    dst.qty -= it.qty
                    if dst.qty == 0:
                        dst.weighted_avg_cost = Decimal("0")
                    dst.save(update_fields=["qty", "weighted_avg_cost"])

                # 回補來源倉
                src = locked_balance(to.tenant, product, to.from_warehouse, create=True)
                # 加權平均:用 unit_cost_at_dispatch 還原
                new_qty = src.qty + it.qty
                if new_qty > 0:
                    old_value = Decimal(src.qty) * src.weighted_avg_cost
                    restore_value = Decimal(it.qty) * it.unit_cost_at_dispatch
                    src.weighted_avg_cost = (
                        (old_value + restore_value) / Decimal(new_qty)
                    ).quantize(CENTS)
                src.qty = new_qty
                src.save(update_fields=["qty", "weighted_avg_cost"])

                StockMovement.objects.create(
                    tenant=to.tenant,
                    product=product,
                    qty=it.qty,
                    movement_type=StockMovement.MovementType.VOID,
                    from_warehouse=to.to_warehouse if is_confirmed else None,
                    to_warehouse=to.from_warehouse,
                    ref_doc_type="transfer_order",
                    ref_doc_id=to.id,
                    note=f"調撥單 {to.no} 作廢({to.get_status_display()}) {product.sku} ×{it.qty}",
                )

        to.is_void = True
        to.save(update_fields=["is_void"])
    return to
