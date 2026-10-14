"""報價連結。跑法:manage.py test apps.trade.test_quote

要守住的(owner 2026-10-14:「報價連結這個想法超棒可以,但是要可以關閉連結分享」;紅隊三條):
1. 一個同行一條;關掉 / 換一條之後舊的打不開;不往來、賣家關掉批發也打不開。關一條不影響別人的。
2. 看到的跟他在平台內看到的一樣:他的價(折數照他的)、他看得到的東西;不出現成本、序號、門市、別人的價。
3. 中古機:同一格、同一個價的合成一行;獨立定價的一台一行、帶編號。每一行的「複製」帶賣家、型號、價、編號與報價時間。
4. 記上次看、看過幾次;每分鐘有上限;不給搜尋引擎收錄、不快取、不載外面的東西。
5. 只有管理員能開關;還原備份之後全部清掉(關掉的舊連結不能自己活過來)。
"""
import re
from decimal import Decimal as D

from django.test import Client, TestCase

from apps.core.money import round_money

from apps.backup.tests.test_backup_restore import _Base as BackupBase
from apps.catalog.models import Product

from . import quote
from .models import TradePartner, TradeQuoteLink, TradeUnit
from .tests import T, _Helpers


class _Quote(_Helpers):
    def setUp(self):
        super().setUp()
        self.open_shop()
        made = self.a.admin.post(T + "partners/external/", {"name": "外面的丁通訊", "contact": "0911-222-333"}, format="json")
        self.assertEqual(made.status_code, 201, made.content.decode())
        self.ding = TradePartner.objects.get(pk=made.json()["partner"]["id"])
        self.path = made.json()["partner"]["quote"]["path"]

    def page(self, path=None, expect=200):
        r = Client().get(path or self.path)
        self.assertEqual(r.status_code, expect, r.content.decode()[:300])
        return r

    def text(self, path=None, expect=200):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", self.page(path, expect).content.decode()))

    def turn(self, partner, do, client=None, expect=200):
        r = (client or self.a.admin).post(f"{T}partners/{partner.id}/quote/", {"do": do}, format="json")
        self.assertEqual(r.status_code, expect, r.content.decode())
        return r.json()


class QuotePageTests(_Quote, TestCase):
    def test_a_new_outside_peer_gets_a_link_that_shows_the_used_phones_by_cell(self):
        units = []
        for sn, grade, battery, note in (("A1", "A", 90, ""), ("A2", "A", 88, ""), ("A3", "A", 85, "背蓋小刮"), ("B1", "B", 90, "")):
            units += self.stock_units(sn, grade=grade, battery=battery, note=note)
        r = self.a.admin.post(T + "units/list/", {"rows": [{"serial": units[2].id, "price": 9100}], "product": self.used.id,
                                                  "cell": {"grade": "A", "noted": "no"}, "cell_price": 12000}, format="json")
        self.assertEqual(r.status_code, 200, r.content.decode())
        self.assertRegex(self.path, r"^/api/trade/quote/[A-Za-z0-9_-]{32}/$")
        r = self.page()
        for header, value in (("Cache-Control", "no-store"), ("X-Robots-Tag", "noindex, nofollow"), ("Referrer-Policy", "no-referrer")):
            self.assertEqual(r[header], value)
        self.assertIn("default-src 'none'", r["Content-Security-Policy"])
        html = r.content.decode()
        self.assertNotRegex(html, r"(src|href)=['\"]https?://")                    # 不載外面的東西
        text = self.text()
        self.assertIn("甲通訊行 報價", text)
        self.assertIn("給 外面的丁通訊", text)
        # 一台一行:成色、電池、備註、價、編號(owner:中古機要能看到電池、備註打的機況)
        ids = {s.serial_no: TradeUnit.objects.get(serial=s).id for s in units}
        self.assertIn(f"A 級 電池 90% 編號 U{ids['A1']} 12,000", text)
        self.assertIn(f"A 級 電池 88% 編號 U{ids['A2']} 12,000", text)
        self.assertIn(f"A 級 電池 85% 背蓋小刮 編號 U{ids['A3']} 9,100", text)
        self.assertIn(f"B 級 電池 90% 編號 U{ids['B1']} 15,000", text)
        self.assertLess(text.index(f"U{ids['A1']}"), text.index(f"U{ids['A2']}"))          # 同成色電池高的在前
        for secret in ("A1", "A2", "A3", "B1", "12000.00", self.wh1.name, "成本"):
            self.assertNotIn(secret, html, secret)
        # 複製的那一句:賣家、型號、哪一格、價、編號、報價時間
        copies = re.findall(r"data-copy='([^']*)'", html)
        self.assertTrue(any(c.startswith("甲通訊行 甲 中古 iPhone 13 128GB A 級 電池 85% 背蓋小刮 9,100 編號 U") and c.endswith(" 報價)") for c in copies), copies)

    def test_the_peer_sees_his_own_price_and_only_what_he_may_see(self):
        self.a.purchase(case_qty=10)
        self.offer(self.a.case)
        self.stock_units("A1")
        TradePartner.objects.filter(pk=self.ding.pk).update(percent=80)
        self.assertIn(f"{self.a.case.name}", self.text())
        price = int(round_money(self.a.case.list_price * D("0.8")))                # 四捨五入(跟伺服器同一個)
        self.assertIn(f"{price:,} 有貨", self.text())
        other = self.a.admin.post(T + "partners/external/", {"name": "外面的戊", "contact": "0922"}, format="json").json()["partner"]
        TradePartner.objects.filter(pk=other["id"]).update(percent=95)
        self.assertIn(f"{int(round_money(self.a.case.list_price * D('0.95'))):,} 有貨", self.text(other["quote"]["path"]))
        # 沒核准的只看得到中古機;賣家改成中古機也只給核准的 → 連中古機都沒有
        TradePartner.objects.filter(pk=self.ding.pk).update(status="guest")
        text = self.text()
        self.assertNotIn(self.a.case.name, text)
        self.assertIn("甲 中古 iPhone 13 128GB", text)
        self.open_shop(units_to_all=False)
        self.assertIn("目前沒有報價", self.text())
        # 顯示數量
        TradePartner.objects.filter(pk=self.ding.pk).update(status="approved")
        self.assertIn("A 級 電池 90% 小刮 編號 U", self.text())                      # 中古機一台一行
        self.assertIn("有貨", self.text())                                          # 沒開「顯示數量」:商品只寫有貨
        self.open_shop(show_qty=True)
        self.assertIn("10 個", self.text())

    def test_names_are_escaped(self):
        Product.objects.filter(pk=self.used.pk).update(name="<script>alert(1)</script> 中古機")
        one, = self.stock_units("A1", note="'><img src=x onerror=alert(2)>")
        # 獨立定價的那一台才會把備註印出來(也進「複製」與搜尋用的屬性)
        self.a.admin.post(T + "units/list/", {"rows": [{"serial": one.id, "price": 9100}]}, format="json")
        html = self.page().content.decode()
        self.assertIn("&#x27;&gt;&lt;img src=x onerror=alert(2)&gt;", html)
        for raw in ("<script>alert(1)", "<img src=x", "'><img"):
            self.assertNotIn(raw, html, raw)
        self.assertIn("&lt;script&gt;", html)
        self.assertRegex(html, r"data-copy='[^']*&#x27;&gt;&lt;img")
        self.assertRegex(html, r"data-q='[^']*&#x27;&gt;&lt;img")

    def test_closing_or_renewing_a_link_shuts_only_that_one(self):
        other = self.a.admin.post(T + "partners/external/", {"name": "外面的戊", "contact": "0922"}, format="json").json()["partner"]
        self.turn(self.ding, "off")
        self.assertIn("連結已關閉", self.text(expect=404))
        self.page(other["quote"]["path"])                                           # 別人的照樣看得到
        self.turn(self.ding, "on")
        self.page()
        renewed = self.turn(self.ding, "new")["partner"]["quote"]
        self.assertNotEqual(renewed["path"], self.path)
        self.page(expect=404)
        self.page(renewed["path"])
        self.page("/api/trade/quote/not-a-real-link-at-all-000000/", expect=404)
        self.page("/api/trade/quote/x/", expect=404)
        for bad in ("maybe", None, ""):
            self.turn(self.ding, bad, expect=400)

    def test_blocked_peer_closed_shop_and_maintenance(self):
        TradePartner.objects.filter(pk=self.ding.pk).update(status="blocked")
        self.page(expect=404)
        TradePartner.objects.filter(pk=self.ding.pk).update(status="approved")
        self.open_shop(is_open=False)
        self.page(expect=404)
        self.open_shop()
        from unittest import mock
        with mock.patch("apps.trade.quote_views.in_maintenance", return_value=True):
            self.assertIn("維護中", self.text(expect=503))

    def test_opens_are_counted_and_limited(self):
        self.page()
        self.page()
        link = TradeQuoteLink.objects.get(partner=self.ding)
        self.assertEqual(link.open_count, 2)
        self.assertIsNotNone(link.opened_at)
        listed = next(p for p in self.a.admin.get(T + "partners/").json()["partners"] if p["id"] == self.ding.id)
        self.assertEqual((listed["quote"]["count"], listed["quote"]["on"], listed["quote"]["path"]), (2, True, self.path))
        for _ in range(quote.PER_MINUTE - 2):
            self.page()
        self.assertIn("請稍後再看", self.text(expect=429))

    def test_only_managers_turn_links_and_only_their_own(self):
        self.turn(self.ding, "off", client=self.a.clerk, expect=403)
        self.turn(self.ding, "off", client=self.b.admin, expect=404)
        self.assertTrue(TradeQuoteLink.objects.get(partner=self.ding).is_on)
        # 平台內的同行也可以開(第一次開會建一條)
        inside = self.approve(self.b)
        self.assertIsNone(next(p for p in self.a.admin.get(T + "partners/").json()["partners"] if p["id"] == inside.id)["quote"])
        self.turn(inside, "off", expect=400)
        path = self.turn(inside, "on")["partner"]["quote"]["path"]
        self.assertIn("給 乙通訊行", self.text(path))


class QuoteBackupTests(BackupBase):
    def test_links_do_not_come_back_with_a_restore(self):
        a = self.a
        self.assertEqual(a.admin.post(T + "settings/", {"is_open": True}, format="json").status_code, 200)
        made = a.admin.post(T + "partners/external/", {"name": "外面的丁", "contact": "0911"}, format="json").json()
        path = made["partner"]["quote"]["path"]
        self.assertEqual(Client().get(path).status_code, 200)
        job = self.backup(a)
        done = self.rollback(a, self.path(job))
        self.assertEqual(done.status, "done", done.error)
        self.assertEqual(TradeQuoteLink.objects.count(), 0)
        self.assertEqual(Client().get(path).status_code, 404)
        self.assertTrue(TradePartner.objects.filter(tenant=a.tenant, name="外面的丁").exists())
