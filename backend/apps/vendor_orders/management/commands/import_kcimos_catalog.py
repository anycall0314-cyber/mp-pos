"""把 kcimos 的商品快照匯成價目表(平台方跑;規則在 `vendor_orders/kcimos.py`)。

    manage.py import_kcimos_catalog 快照.json --only-for JB            # 先看會做什麼(不寫)
    manage.py import_kcimos_catalog 快照.json --only-for JB --apply    # 真的寫進去

快照檔有特定帳號的進價:不要放進版本庫,放在伺服器上跑。
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.vendor_orders import kcimos


class Command(BaseCommand):
    help = "把 kcimos 的商品快照匯成半自動廠商的價目表(只給指定的公司)"

    def add_arguments(self, parser):
        parser.add_argument("snapshot", help="kcimos完整商品.json 的路徑")
        parser.add_argument("--only-for", required=True, help="這份價目給哪幾家公司(公司代碼,逗號分開),例 JB")
        parser.add_argument("--apply", action="store_true", help="真的寫進資料庫(沒加就只看會做什麼)")
        parser.add_argument("--database-must-be", default="", help="資料庫的名字要是這個才跑(防止對錯資料庫)")

    def handle(self, *args, **options):
        must = options["database_must_be"]
        if must and connection.settings_dict["NAME"] != must:
            raise CommandError(f"現在連的資料庫是 {connection.settings_dict['NAME']},不是 {must}")
        try:
            with open(options["snapshot"], encoding="utf-8") as f:
                snapshot = json.load(f)
        except (OSError, ValueError) as exc:
            raise CommandError(f"快照檔讀不出來:{exc}") from None
        codes = options["only_for"].split(",")
        try:
            todo = kcimos.apply(snapshot, codes) if options["apply"] else kcimos.plan(snapshot, codes)
        except kcimos.SnapshotError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            f"{'已匯入' if options['apply'] else '預覽(沒有寫)'}:共 {len(todo['rows'])} 項 —— 新增 {len(todo['new'])}、更新 {len(todo['changed'])}、"
            f"一樣 {todo['same']};其中停用 {todo['stopped']}、沒有參考價 {todo['unpriced']};"
            f"價目表上有、快照裡沒有的 {todo['left_alone']} 項沒有動。給:{'、'.join(todo['codes'])}"
            + ("" if todo["vendor_exists"] or not options["apply"] else ";kcimos 這家廠商是這一次建的"))
