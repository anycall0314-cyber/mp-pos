"""配件 → 相容機型規則比對測試(離線可跑,不需要 DB 有資料)。

證明:
1. 縮寫查表認得店內寫法(IP15PM / SAM/S24U / PIXEL-8)。
2. `P` 的歧義由「那一代有沒有 Pro」決定,不是寫死:iPhone 7 沒有 Pro → IP7P 是 Plus;
   iPhone 11 有 Pro → IP11P 是 Pro。**這條錯了會把 Plus 的配件掛到 Pro 上。**
3. 一條品名列多款機時全部掛到(含後面省略前綴的寫法 IP16E/17E)。
4. 通用配件(線材/支架)不掛機型。
5. 認不出來就回 UNRESOLVED,不硬湊一個像的。
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from .accessory_model_match import (
    GENERIC,
    MATCHED,
    UNRESOLVED,
    build_index,
    classify,
)


def M(pk, name):
    """假的機型主檔一筆;build_index 只用到 id / name。"""
    return SimpleNamespace(id=pk, name=name)


# 涵蓋「有 Pro 的世代」與「沒有 Pro 的世代」兩種,才測得出 P 的歧義。
MODELS = [
    M(1, "iPhone 7"),
    M(2, "iPhone 7 Plus"),
    M(3, "iPhone 11"),
    M(4, "iPhone 11 Pro"),
    M(5, "iPhone 11 Pro Max"),
    M(6, "iPhone 15 Pro Max"),
    M(7, "iPhone 16e"),
    M(8, "iPhone 17e"),
    M(9, "iPhone 10 S Max"),
    M(10, "Galaxy S 24 Ultra"),
    M(11, "Galaxy S 24+"),
    M(12, "Pixel 8"),
    M(13, "iPhone 6 s Plus"),
    M(14, "Galaxy S 4 mini"),
]
NAME = {m.id: m.name for m in MODELS}


class AbbrevIndexTests(SimpleTestCase):
    def setUp(self):
        self.index = build_index(MODELS)

    def hit(self, name):
        kind, ids, _ = classify(name, self.index)
        return kind, {NAME[i] for i in ids}

    def test_basic_abbrev(self):
        self.assertEqual(self.hit("IMOS/IP15PM/透"), (MATCHED, {"iPhone 15 Pro Max"}))
        self.assertEqual(self.hit("DAP/SAM/S24U/鋁合金/綠"), (MATCHED, {"Galaxy S 24 Ultra"}))
        self.assertEqual(self.hit("滿/GOOGLE/PIXEL-8/黑"), (MATCHED, {"Pixel 8"}))
        self.assertEqual(self.hit("SAM/S24+/桃"), (MATCHED, {"Galaxy S 24+"}))

    def test_p_means_plus_when_generation_has_no_pro(self):
        """iPhone 7 沒有 Pro 機,所以店內的 IP7P 是 7 Plus。"""
        self.assertEqual(self.hit("PG/IP7P/坦克/黑"), (MATCHED, {"iPhone 7 Plus"}))

    def test_p_means_pro_when_generation_has_pro(self):
        """iPhone 11 有 Pro 機,所以 IP11P 是 11 Pro,不是 Plus(11 根本沒有 Plus)。"""
        self.assertEqual(self.hit("滿/IP11P/霧"), (MATCHED, {"iPhone 11 Pro"}))

    def test_pro_max_not_confused_with_pro(self):
        self.assertEqual(self.hit("IP11PM/黑"), (MATCHED, {"iPhone 11 Pro Max"}))

    def test_xs_max_spellings(self):
        """主檔把 XS Max 寫成「iPhone 10 S Max」,店內寫 IPXSMAX 或簡寫 IPXSM。"""
        for n in ("滿/IPXSMAX/那盾/3D/黑", "滿/IPXSM/3D"):
            self.assertEqual(self.hit(n), (MATCHED, {"iPhone 10 S Max"}), n)

    def test_multi_model_all_attached(self):
        kind, names = self.hit("IMOS/IP7/IP11/點膠/黑")
        self.assertEqual(kind, MATCHED)
        self.assertEqual(names, {"iPhone 7", "iPhone 11"})

    def test_prefix_dropped_continuation(self):
        """一條列多款時後面會省略 IP 前綴(IP16E/17E)。"""
        kind, names = self.hit("IP16E/17E/柔幻磁吸/透")
        self.assertEqual(kind, MATCHED)
        self.assertEqual(names, {"iPhone 16e", "iPhone 17e"})

    def test_hyphen_ignored(self):
        """真實品名同一款會寫 `S4-MINI` 也會寫 `S4MINI`,連字號不當分隔符而是抹掉。"""
        self.assertEqual(self.hit("SAM/S4-MINI/白"), (MATCHED, {"Galaxy S 4 mini"}))

    def test_six_s_plus_real_spellings(self):
        """6s Plus 在真實品名裡寫成 IP6SP 或 IP6S+ 兩種,兩種都要認。"""
        for n in ("IP6SP-軟質邊框", "H.K./IP6S+"):
            self.assertEqual(self.hit(n), (MATCHED, {"iPhone 6 s Plus"}), n)

    def test_generic_accessories_have_no_model(self):
        for n in ("MRCOQ/A轉C/27W/2M", "YESIDO/C233/磁吸手機支架",
                  "BIAZE/一拖三/編織/白/100W/2M", "EARPODS/3.5MM"):
            kind, names = self.hit(n)
            self.assertEqual(kind, GENERIC, n)
            self.assertEqual(names, set())

    def test_unknown_model_is_not_forced(self):
        """主檔沒有的機(老三星)要回 UNRESOLVED,不可以硬湊一個像的。"""
        kind, names = self.hit("SAM/NOTE2/霧")
        self.assertEqual(kind, UNRESOLVED)
        self.assertEqual(names, set())

    def test_bare_number_does_not_match(self):
        """裸數字在品名裡多半是吋數或代數,不可以當成機型世代。"""
        kind, names = self.hit("平板/IPAD7/8/10.2吋")
        self.assertEqual(names, set())
        self.assertEqual(kind, UNRESOLVED)

    def test_brand_token_not_taken_as_model(self):
        """X-LEVEL 是品牌;抹連字號前要先認出來,否則會變成 XLEVEL 認不得。"""
        kind, _ = self.hit("X-LEVEL/反光繩/灰")
        self.assertIn(kind, (GENERIC, UNRESOLVED))
