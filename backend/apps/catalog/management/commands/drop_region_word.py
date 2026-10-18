"""品名、規格拿掉「台版」(owner 2026-10-17:「手機平板穿戴幾乎百分之99以上一定是台版，不需要去特別多個欄位去填他是哪個國家版本，品名也不需要」)。

    python manage.py drop_region_word --tenant JB             # 試算(不寫)
    python manage.py drop_region_word --tenant JB --confirm   # 寫進去(可以重跑)

只拿掉品名裡單獨一段的「台版 / 臺版 / 台灣版」(`device_expand.bare_name`),規格一起拿掉,地區版本欄是台版的清掉。
拿掉之後跟另一個商品同名的不改、列出來(同一支建了兩份,要人決定留哪一個)。港版、美版…不動。
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.device_expand import bare_name
from apps.catalog.models import Product
from apps.tenants.models import Tenant

TW = {"台版", "臺版", "台灣版"}


def drop_region_word(tenant, *, confirm=False) -> tuple[int, list[tuple[str, str]]]:
    """回 (改了幾個, 撞名沒改的 [(品號, 品名)])。"""
    with transaction.atomic():
        qs = Product.objects.for_tenant(tenant)
        taken = set(qs.values_list("name", flat=True))
        changed, clashes = 0, []
        for p in qs.filter(name__regex=r"(台版|臺版|台灣版)").select_for_update().order_by("pk"):
            new = bare_name(p.name)
            if new == p.name:
                continue                       # 黏在別的字上(「XX台版」)不是單獨一段,不動
            if new in taken:
                clashes.append((p.sku, p.name))
                continue
            taken.discard(p.name)
            taken.add(new)
            p.name, p.spec = new, bare_name(p.spec)
            if p.region_version.strip() in TW:
                p.region_version = ""
            p.save(update_fields=["name", "spec", "region_version", "updated_at"])
            changed += 1
        if not confirm:
            transaction.set_rollback(True)
    return changed, clashes


class Command(BaseCommand):
    help = "品名、規格拿掉「台版」(手機、平板、穿戴幾乎都是台版,不寫)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼(例:JB)")
        parser.add_argument("--confirm", action="store_true", help="真的寫進去(沒有這個只試算)")

    def handle(self, *args, **opts):
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"沒有這家公司:{opts['tenant']}")
        changed, clashes = drop_region_word(tenant, confirm=opts["confirm"])
        self.stdout.write(f"{tenant.code}:{'寫好了' if opts['confirm'] else '試算(沒有寫入)'},拿掉台版 {changed} 個")
        if clashes:
            self.stdout.write(f"  拿掉之後跟別的商品同名、沒改的 {len(clashes)} 個:")
            for sku, name in clashes:
                self.stdout.write(f"    {sku} {name}")
