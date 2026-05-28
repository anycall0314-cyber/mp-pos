"""清掉測試用的商品 / 庫存資料,並 seed 常見品牌與系列主檔。

用法:
  python manage.py reset_catalog --tenant <code> [--yes]

清掉:
  Product / Category / StockBalance / StockMovement / ProductSerial /
  ProductRelation / PartTemplate / PartTemplateItem /
  PurchaseOrder / PurchaseOrderItem /
  SalesOrder / SalesOrderItem / SalesOrderPayment / SalesReturn / SalesReturnItem /
  TransferOrder / TransferOrderItem /
  RepairOrder / RepairOrderPart /
  Brand / PhoneSeries

保留:
  Tenant / UserProfile / SalesPerson / Customer / Member / Supplier /
  Warehouse / InvoiceType / PaymentMethod / 系統設定類

seed 內容:
  常見品牌 8 個 + 每個品牌底下對應的常見系列
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Tenant


DEFAULT_BRANDS = [
    {
        "code": "apple",
        "name": "Apple",
        "sort": 1,
        "series": [
            ("iphone", "iPhone", 1),
            ("ipad", "iPad", 2),
            ("watch", "Watch", 3),
        ],
    },
    {
        "code": "samsung",
        "name": "Samsung",
        "sort": 2,
        "series": [
            ("s", "Galaxy S", 1),
            ("a", "Galaxy A", 2),
            ("z", "Galaxy Z", 3),
            ("note", "Galaxy Note", 4),
            ("m", "Galaxy M", 5),
            ("fe", "Galaxy FE", 6),
            ("tab", "Galaxy Tab", 7),
        ],
    },
    {
        "code": "xiaomi",
        "name": "小米",
        "sort": 3,
        "series": [
            ("mi", "Mi", 1),
            ("redmi", "Redmi", 2),
            ("redmi-note", "Redmi Note", 3),
            ("poco", "POCO", 4),
        ],
    },
    {
        "code": "oppo",
        "name": "OPPO",
        "sort": 4,
        "series": [
            ("reno", "Reno", 1),
            ("find", "Find", 2),
            ("a", "A 系列", 3),
        ],
    },
    {
        "code": "vivo",
        "name": "VIVO",
        "sort": 5,
        "series": [
            ("v", "V 系列", 1),
            ("y", "Y 系列", 2),
            ("x", "X 系列", 3),
        ],
    },
    {
        "code": "asus",
        "name": "ASUS",
        "sort": 6,
        "series": [
            ("zenfone", "Zenfone", 1),
            ("rog", "ROG Phone", 2),
        ],
    },
    {
        "code": "google",
        "name": "Google",
        "sort": 7,
        "series": [
            ("pixel", "Pixel", 1),
        ],
    },
    {
        "code": "sony",
        "name": "Sony",
        "sort": 8,
        "series": [
            ("xperia", "Xperia", 1),
        ],
    },
]


class Command(BaseCommand):
    help = "清測試資料 + seed 常見品牌與系列主檔(per-tenant)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="目標 tenant code")
        parser.add_argument(
            "--yes",
            action="store_true",
            help="跳過確認直接執行",
        )
        parser.add_argument(
            "--skip-clear",
            action="store_true",
            help="只 seed 不清資料",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        tenant_code = opts["tenant"]
        try:
            tenant = Tenant.objects.get(code=tenant_code)
        except Tenant.DoesNotExist:
            raise CommandError(f"找不到 tenant code={tenant_code!r}")

        if not opts["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\n即將清除 tenant『{tenant.name}』({tenant_code}) 的商品 / 庫存 / "
                    f"進銷/維修 相關資料,並 seed 常見品牌與系列主檔。\n"
                    f"輸入大寫 YES 確認:"
                )
            )
            ans = input().strip()
            if ans != "YES":
                self.stdout.write(self.style.ERROR("已取消"))
                return

        if not opts["skip_clear"]:
            self._clear(tenant)
        self._seed(tenant)
        self.stdout.write(self.style.SUCCESS("\n完成 ✓"))

    def _clear(self, tenant):
        from apps.catalog.models import (
            Brand,
            Category,
            PartTemplate,
            PartTemplateItem,
            PhoneSeries,
            Product,
            ProductRelation,
        )
        from apps.inventory.models import (
            ProductSerial,
            StockBalance,
            StockMovement,
        )
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderItem
        from apps.repairs.models import RepairOrder, RepairOrderPart
        from apps.sales.models import (
            SalesOrder,
            SalesOrderItem,
            SalesOrderPayment,
            SalesReturn,
            SalesReturnItem,
        )
        from apps.transfers.models import TransferOrder, TransferOrderItem

        models_to_clear = [
            # 子單先清
            ("維修零件", RepairOrderPart),
            ("維修單", RepairOrder),
            ("銷退項", SalesReturnItem),
            ("銷退單", SalesReturn),
            ("銷貨付款", SalesOrderPayment),
            ("銷貨項", SalesOrderItem),
            ("銷貨單", SalesOrder),
            ("進貨項", PurchaseOrderItem),
            ("進貨單", PurchaseOrder),
            ("調撥項", TransferOrderItem),
            ("調撥單", TransferOrder),
            ("庫存異動", StockMovement),
            ("庫存餘額", StockBalance),
            ("商品序號", ProductSerial),
            ("商品關聯", ProductRelation),
            ("零件範本項", PartTemplateItem),
            ("零件範本", PartTemplate),
            ("商品", Product),
            ("類別", Category),
            ("系列主檔", PhoneSeries),
            ("品牌主檔", Brand),
        ]
        self.stdout.write("── 清除既有資料 ──")
        for label, M in models_to_clear:
            n, _ = M.objects.filter(tenant=tenant).delete()
            self.stdout.write(f"  {label}: {n}")
        # 重置類別流水
        tenant.next_repair_seq = 1
        tenant.save(update_fields=["next_repair_seq"])

    def _seed(self, tenant):
        from apps.catalog.models import Brand, PhoneSeries

        self.stdout.write("\n── Seed 品牌 + 系列主檔 ──")
        for b in DEFAULT_BRANDS:
            brand, _ = Brand.objects.update_or_create(
                tenant=tenant,
                code=b["code"],
                defaults={
                    "name": b["name"],
                    "sort_order": b["sort"],
                    "is_active": True,
                },
            )
            self.stdout.write(f"  品牌 {brand.code} ({brand.name})")
            for s_code, s_name, s_sort in b["series"]:
                PhoneSeries.objects.update_or_create(
                    tenant=tenant,
                    brand=brand,
                    code=s_code,
                    defaults={
                        "name": s_name,
                        "sort_order": s_sort,
                        "is_active": True,
                    },
                )
                self.stdout.write(f"    └ 系列 {s_code} ({s_name})")
