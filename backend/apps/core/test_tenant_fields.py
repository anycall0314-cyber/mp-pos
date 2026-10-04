"""每一個給公司用的序列化器,關聯欄位都只能接受「這家公司」的資料。

跟備份的登記表一樣反過來做:掃過所有 app 的 serializers 模組裡每一個序列化器(含巢狀明細),
只要有一個可寫的關聯欄位指向有 tenant 欄位的表、卻沒有限縮到 request.tenant,測試就紅。
新增序列化器忘了掛 TenantScopedRelatedFieldsMixin 會在這裡被擋下。
平台後台(apps/tenants/platform_views.py)本來就要跨公司操作,不在掃描範圍。
"""
import importlib
import inspect

from django.apps import apps as django_apps
from django.test import RequestFactory, TestCase
from rest_framework import serializers

from apps.tenants.models import Tenant

# 刻意不限縮的(要寫明理由)
EXEMPT = {
}

# 可寫的關聯欄位指向「沒有公司欄位的表」(例如帳號表)時,mixin 管不到:
# 要嘛改唯讀,要嘛在這裡寫明為什麼可以讓呼叫端指定
ALLOWED_GLOBAL_TARGETS = {
}


def _has_tenant(model):
    return any(f.name == "tenant" for f in model._meta.get_fields())


def unscoped_fields(serializer, tenant, path=""):
    bad = []
    for name, field in serializer.fields.items():
        where = f"{path}{name}"
        if isinstance(field, serializers.ListSerializer):
            if isinstance(field.child, serializers.BaseSerializer) and not field.read_only:
                bad += unscoped_fields(field.child, tenant, where + ".")
            continue
        if isinstance(field, serializers.BaseSerializer):
            if not field.read_only:
                bad += unscoped_fields(field, tenant, where + ".")
            continue
        target = field.child_relation if isinstance(field, serializers.ManyRelatedField) else field
        if not isinstance(target, serializers.RelatedField) or field.read_only:
            continue
        if target.queryset is None:
            continue
        qs = target.get_queryset()
        if not _has_tenant(qs.model):
            bad.append(f"{where}(指向沒有公司欄位的表 {qs.model._meta.label})")
            continue
        sql = str(qs.query)
        if f'"tenant_id" = {tenant.pk}' not in sql:
            bad.append(where)
    return bad


def company_serializers():
    for app in django_apps.get_app_configs():
        if not app.name.startswith("apps."):
            continue
        # serializers.py 之外,views.py 裡也可能定義輸入用的序列化器
        # (平台後台在 platform_views.py,本來就跨公司,不掃)
        for part in ("serializers", "views"):
            try:
                module = importlib.import_module(f"{app.name}.{part}")
            except ModuleNotFoundError:
                continue
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(cls, serializers.BaseSerializer)
                    and cls.__module__ == module.__name__
                    and not name.startswith("_")
                ):
                    yield f"{module.__name__}.{name}", cls


class TenantScopedFieldsTests(TestCase):
    def test_every_company_serializer_only_accepts_this_companys_records(self):
        tenant = Tenant.objects.create(name="甲", code="scope-a")
        request = RequestFactory().post("/")
        request.tenant = tenant
        found, problems = 0, []
        for label, cls in company_serializers():
            if label in EXEMPT:
                continue
            found += 1
            try:
                ser = cls(context={"request": request})
            except TypeError:
                continue
            for field in unscoped_fields(ser, tenant):
                if f"{label}.{field.split('(')[0]}" not in ALLOWED_GLOBAL_TARGETS:
                    problems.append(f"{label}.{field}")
        self.assertGreater(found, 40)
        self.assertEqual(problems, [], "這些欄位會接受別家公司的編號:\n" + "\n".join(problems))


class StoreLockTests(TestCase):
    def test_every_store_scoped_create_checks_the_store_lock(self):
        """有門市鎖的 viewset 自己寫了 perform_create 的,一定要呼叫 check_create_warehouse()
        (否則鎖在自己門市的店員能在別家門市建單)。"""
        from django.urls import get_resolver

        from apps.core.warehouse_scoping import WarehouseScopedMixin

        seen, missing = set(), []

        def walk(patterns):
            for p in patterns:
                if hasattr(p, "url_patterns"):
                    walk(p.url_patterns)
                    continue
                cls = getattr(p.callback, "cls", None)
                if cls is None or cls in seen or not issubclass(cls, WarehouseScopedMixin):
                    continue
                seen.add(cls)
                own = cls.__dict__.get("perform_create")
                if own is not None and "check_create_warehouse" not in inspect.getsource(own):
                    missing.append(cls.__name__)

        walk(get_resolver().url_patterns)
        self.assertGreaterEqual(len(seen), 8)
        self.assertEqual(missing, [])
