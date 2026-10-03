"""用規則查表把配件掛到相容機型(`ProductRelation`)。

沒有相容機型,「這張進貨單的這一行是哪個商品」就只能靠品名模糊比對,
而配件料號(`IMOS/IP15PM/透`)跟手機主檔(`iPhone 15 Pro Max ...`)是兩套寫法,
模糊比對跨不過去。這支先把地基補起來。

縮寫慣例與刻意不做的事,見 `apps/catalog/accessory_model_match.py` 的說明。

用法:
    # 預覽(不寫入,只報告各族群幾筆)
    python manage.py match_accessory_models --tenant default

    # 正式寫入
    python manage.py match_accessory_models --tenant default --confirm

    # 看對不到的片段排行(決定要不要補機型主檔)
    python manage.py match_accessory_models --tenant default --show-unresolved 40

設計原則:
- **可重複執行**:`ProductRelation` 以 (tenant, host_model_key, accessory_product) 唯一,
  已存在的略過,不會重複建。
- **全程 dry-run**,`--confirm` 才寫入。
- **只建關聯,不改商品**:不動 `Product.phone_model`、不改品名、不建商品。
- **對不到就不寫**:查表對不到的留著讓人看,不硬湊一個像的機型。
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.accessory_model_match import (
    GENERIC,
    MATCHED,
    UNRESOLVED,
    build_index,
    classify,
)
from apps.catalog.models import Category, PhoneModel, Product, ProductRelation
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "用縮寫查表把配件掛到相容機型(ProductRelation),不建立任何商品"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="租戶 code 或 name")
        parser.add_argument("--confirm", action="store_true", help="正式寫入;不加則只預覽")
        parser.add_argument("--show-unresolved", type=int, default=0,
                            help="另外列出對不到的片段排行前 N 名")

    def handle(self, *args, **opts):
        confirm = opts["confirm"]
        tenant = self._resolve_tenant(opts["tenant"])

        models = list(PhoneModel.objects.for_tenant(tenant).filter(is_active=True))
        if not models:
            raise CommandError(
                f"租戶 {tenant.code} 沒有任何機型主檔。"
                f"先跑 sync_phone_models 把機型建起來,否則沒有東西可以對。"
            )
        index = build_index(models)
        name_of = {m.id: m.name for m in models}
        key_of = {m.id: m.match_key for m in models}

        # 哪些類別要掛機型,由 `Category.needs_host_model` 決定(類別設定頁可改),
        # 不在這裡寫死類別名稱:每個租戶的類別命名不一樣。
        skip_cat_ids = list(
            Category.objects.for_tenant(tenant)
            .filter(needs_host_model=False).values_list("id", flat=True)
        )
        accessories = list(
            Product.objects.for_tenant(tenant)
            .filter(is_active=True)
            .exclude(category_id__in=skip_cat_ids)
            .only("id", "name")
        )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"租戶:{tenant.code} {tenant.name} | "
            f"模式:{'正式寫入' if confirm else 'DRY-RUN 預覽'} | "
            f"機型主檔 {len(models)} 筆 / 縮寫索引 {len(index)} 個 | "
            f"配件 {len(accessories)} 筆"
        ))

        # 已存在的關聯先撈出來,避免逐筆查 DB。
        existing = set(
            ProductRelation.objects.for_tenant(tenant)
            .values_list("accessory_product_id", "host_model_key")
        )

        n_matched = n_generic = n_unresolved = 0
        to_create = []
        unresolved_tokens: dict[str, int] = {}
        for p in accessories:
            kind, ids, unresolved = classify(p.name, index)
            if kind == GENERIC:
                n_generic += 1
                continue
            if kind == UNRESOLVED:
                n_unresolved += 1
                for t in unresolved:
                    unresolved_tokens[t] = unresolved_tokens.get(t, 0) + 1
                continue
            n_matched += 1
            for mid in sorted(ids):
                key = key_of[mid]
                if (p.id, key) in existing:
                    continue
                existing.add((p.id, key))
                to_create.append(ProductRelation(
                    tenant=tenant,
                    host_model_id=mid,
                    host_model_key=key,
                    accessory_product=p,
                ))

        if confirm and to_create:
            with transaction.atomic():
                ProductRelation.objects.bulk_create(to_create, batch_size=500)

        self.stdout.write("")
        self.stdout.write(
            f"  規則對到機型   {n_matched:>5} 筆配件 → 要建 {len(to_create)} 筆相容關聯")
        self.stdout.write(f"  通用配件       {n_generic:>5} 筆(不需要機型)")
        self.stdout.write(f"  對不到         {n_unresolved:>5} 筆(留給人看,沒有硬湊)")

        top = opts["show_unresolved"]
        if top:
            self.stdout.write("")
            self.stdout.write(f"對不到的片段前 {top} 名(出現次數):")
            for t, c in sorted(unresolved_tokens.items(), key=lambda x: -x[1])[:top]:
                self.stdout.write(f"    {t:<16}{c}")

        if confirm:
            self.stdout.write(self.style.SUCCESS(
                f"\n已建立 {len(to_create)} 筆相容關聯"))
        else:
            self.stdout.write(self.style.NOTICE(
                "\n(DRY-RUN,未寫入。加 --confirm 才正式建立)"))

    def _resolve_tenant(self, key):
        t = Tenant.objects.filter(code=key).first() or Tenant.objects.filter(name=key).first()
        if t is None:
            raise CommandError(
                f"找不到租戶 code/name={key};現有:"
                f"{[f'{x.code}({x.name})' for x in Tenant.objects.all()]}"
            )
        return t
