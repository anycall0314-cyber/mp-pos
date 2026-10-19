"""把舊 POS 的會員整批帶進來:一位舊會員建一位 MP 會員並對照(舊消費就會出現在那位會員的頁面上)。

    # 試算(不寫任何東西)
    python manage.py bring_in_legacy_members --tenant 公司代碼
    # 真的做
    python manage.py bring_in_legacy_members --tenant 公司代碼 --confirm
    # 只帶 2023-10-01 之後還有消費的、而且有電話的
    python manage.py bring_in_legacy_members --tenant 公司代碼 --since 2023-10-01 --require-phone
    # 收回整批帶入的(被用過的會員不刪)
    python manage.py bring_in_legacy_members --tenant 公司代碼 --undo [--confirm]

規則在 `apps/legacy/mapping.py` 的 `bring_in_members` / `take_back_members`。先要用 `import_legacy_history` 把舊消費匯進來。
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.legacy import mapping
from apps.legacy.models import LegacyMember, MapStatus
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "舊 POS 會員整批建成 MP 會員並對照(預設試算,--confirm 才寫入)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="公司代碼")
        parser.add_argument("--since", help="只帶這一天(YYYY-MM-DD)之後還有消費的舊會員")
        parser.add_argument("--require-phone", action="store_true", help="只帶有電話的")
        parser.add_argument("--undo", action="store_true", help="收回整批帶入的(被用過的會員不刪)")
        parser.add_argument("--confirm", action="store_true", help="真的寫入(沒有就只試算)")

    def handle(self, *args, **opts):
        tenant = Tenant.objects.filter(code=opts["tenant"]).first()
        if tenant is None:
            raise CommandError(f"找不到公司:{opts['tenant']}")
        since = None
        if opts["since"]:
            try:
                since = date.fromisoformat(opts["since"])
            except ValueError:
                raise CommandError("--since 要是 YYYY-MM-DD") from None
        write = opts["confirm"]
        mode = "寫入" if write else "試算(沒有寫入任何東西)"
        total = LegacyMember.objects.filter(tenant=tenant).count()
        mapped = LegacyMember.objects.filter(tenant=tenant, status=MapStatus.CONFIRMED).count()
        self.stdout.write(f"公司 {tenant.code}「{tenant.name}」|{mode}|舊會員 {total} 位,已經對照 {mapped} 位")
        if opts["undo"]:
            if since or opts["require_phone"]:
                raise CommandError("--undo 不能跟 --since / --require-phone 一起用")
            r = mapping.take_back_members(tenant, write=write)
            self.stdout.write(
                f"收回:刪掉整批帶入時新建、沒被用過的會員 {r['removed']} 位;"
                f"只解除對照(原本就有的會員){r['unlinked']} 位;已經被用過、不動的 {r['kept']} 位"
            )
        else:
            r = mapping.bring_in_members(tenant, since=since, require_phone=opts["require_phone"], write=write)
            self.stdout.write(
                f"新建會員並對照 {r['created']} 位(其中沒有電話的 {r['no_phone']} 位);"
                f"對照到原本就有的會員(電話與姓名都一樣){r['linked']} 位;這次沒有帶的 {r['left']} 位"
            )
        if not write:
            self.stdout.write("這是試算。確認數字之後加上 --confirm 才會真的做。")
