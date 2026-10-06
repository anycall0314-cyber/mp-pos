"""商品照片:暫存、隨商品存檔、手機配對。

要守住的事:照片不會掛錯商品(換商品 / 取消 / 存完之後,那支手機傳不進來)、取消與存檔失敗不動到原本的照片、
同一張重試不變兩張、取消過的不會復活、重送不建第二個品號。
"""
import shutil
import threading
import tempfile
from datetime import timedelta
from unittest import mock
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.backup.models import TenantMaintenance
from apps.backup.registry import check_registry
from apps.backup.tests.factory import Company
from apps.catalog.models import Product

from . import imaging, services
from .models import PhotoDraft, PhotoUpload, ProductPhoto
from .services import PhotoRuleError

MEDIA = tempfile.mkdtemp(prefix="mppos-photo-test-")


def picture(size=(800, 600), color=(200, 30, 30), fmt="JPEG", name="a.jpg", exif=None, mode="RGB"):
    img = Image.new(mode, size, color)
    buf = BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buf, fmt, **kwargs)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def tearDownModule():
    shutil.rmtree(MEDIA, ignore_errors=True)


class ImagingTests(TestCase):
    def test_photo_taken_sideways_is_stored_upright(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # 手機直拍:檔案是橫的,靠這個標記轉 90 度
        full, thumb, w, h = imaging.process(picture(size=(800, 600), exif=exif))
        self.assertEqual(Image.open(BytesIO(full)).size, (600, 800))
        self.assertEqual((w, h), (600, 800))
        self.assertLessEqual(max(Image.open(BytesIO(thumb)).size), imaging.THUMB_EDGE)

    def test_big_photo_is_shrunk_but_keeps_its_shape(self):
        full, _thumb, w, h = imaging.process(picture(size=(4800, 3600)))
        self.assertEqual(Image.open(BytesIO(full)).size, (2400, 1800))
        self.assertEqual((w, h), (2400, 1800))

    def test_transparent_png_and_webp_are_accepted(self):
        full, *_ = imaging.process(picture(fmt="PNG", name="a.png", mode="RGBA", color=(0, 0, 0, 0)))
        img = Image.open(BytesIO(full))
        self.assertEqual((img.format, img.mode), ("JPEG", "RGB"))
        self.assertEqual(img.getpixel((5, 5)), (255, 255, 255))  # 透明鋪白底
        imaging.process(picture(fmt="WEBP", name="a.webp"))

    def test_png_that_marks_one_colour_as_transparent_gets_a_white_background(self):
        # 不是 RGBA、而是「把某一個顏色當透明」的 PNG:透明的地方要鋪白底,不能變黑
        img = Image.new("RGB", (40, 40), (0, 0, 0))
        buf = BytesIO()
        img.save(buf, "PNG", transparency=(0, 0, 0))
        full, _thumb, _w, _h = imaging.process(SimpleUploadedFile("t.png", buf.getvalue()))
        self.assertGreater(min(Image.open(BytesIO(full)).convert("RGB").getpixel((20, 20))), 240)

    def test_iphone_heic_is_readable(self):
        if not imaging.HEIF_OK:
            self.skipTest("沒有裝 pillow-heif")
        buf = BytesIO()
        Image.new("RGB", (640, 480), (10, 120, 200)).save(buf, "HEIF")
        full, *_ = imaging.process(SimpleUploadedFile("IMG_0001.HEIC", buf.getvalue()))
        self.assertEqual(Image.open(BytesIO(full)).format, "JPEG")

    def test_things_that_are_not_photos_are_refused(self):
        for bad in (b"", b"%PDF-1.7 not a picture", b"\xff\xd8\xff broken jpeg"):
            with self.assertRaises(imaging.PhotoError):
                imaging.process(SimpleUploadedFile("x.jpg", bad))
        with self.assertRaises(imaging.PhotoError):  # 副檔名是 jpg、內容是 GIF:看內容
            imaging.process(picture(fmt="GIF", name="x.jpg", mode="P", color=1))


@override_settings(MEDIA_ROOT=MEDIA)
class Base(TestCase):
    def setUp(self):
        self.c = Company("a", "甲通訊行", "甲")
        self.api = self.c.admin
        self.new_product = {
            "name": "透明防摔保護殼", "category": self.c.cat_case.id, "list_price": "390",
        }

    # ── 小工具 ──
    def draft(self, product=None, client=None, **body):
        if product is not None:
            body["product"] = product.id
        resp = (client or self.api).post("/api/v1/photo-drafts/", body, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()["uid"]

    def upload(self, uid, key, expect=201, client=None, file=None):
        resp = (client or self.api).post(
            f"/api/v1/photo-drafts/{uid}/uploads/",
            {"uid": key, "file": file or picture()}, format="multipart")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def act(self, draft_uid, action, expect=200, **body):
        resp = self.api.post(f"/api/v1/photo-drafts/{draft_uid}/{action}/", body, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def state(self, uid):
        return self.api.get(f"/api/v1/photo-drafts/{uid}/").json()

    def create(self, photos=None, expect=201, **extra):
        body = {**self.new_product, **extra}
        if photos is not None:
            body["photos"] = photos
        resp = self.api.post("/api/v1/products/", body, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def photos_of(self, product_id):
        return self.api.get(f"/api/v1/product-photos/?product={product_id}").json()

    def phone(self, token, device="phone-A"):
        c = APIClient()
        c.credentials(HTTP_X_PAIR_TOKEN=token, HTTP_X_PAIR_DEVICE=device)
        return c

    def pair(self, uid, device="phone-A", expect=200):
        token = self.act(uid, "pair")["pair_token"]
        phone = self.phone(token, device)
        resp = phone.post("/api/v1/photo-pair/claim/")
        self.assertEqual(resp.status_code, expect, resp.content)
        return token, phone

    def phone_upload(self, phone, key, expect=200):
        resp = phone.post("/api/v1/photo-pair/upload/", {"uid": key, "file": picture()},
                          format="multipart")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()


class SaveWithProductTests(Base):
    def test_new_product_gets_its_photos_in_one_save(self):
        uid = self.draft(label="透明防摔保護殼")
        self.upload(uid, "front")
        self.upload(uid, "back")
        self.upload(uid, "port")
        product = self.create({"draft": uid, "items": [
            {"upload": "back", "caption": "背面"},
            {"upload": "front", "caption": "正面", "is_primary": True},
        ]})
        saved = self.photos_of(product["id"])
        # 主圖排最前面,其餘照清單順序;沒放進清單的那一張(port)不掛
        self.assertEqual([(p["caption"], p["is_primary"]) for p in saved],
                         [("正面", True), ("背面", False)])
        self.assertEqual(product["photo_count"], 2)
        listed = self.api.get(f"/api/v1/products/?search={product['sku']}").json()["results"][0]
        self.assertEqual(listed["photo_count"], 2)
        self.assertTrue(listed["photo_thumb"].startswith("/api/v1/photo-file/"))
        # 照片檔讀得到(網址帶簽章,不用登入的憑證);亂改的網址讀不到
        anon = APIClient()
        got = anon.get(saved[0]["image_url"])
        self.assertEqual((got.status_code, got["Content-Type"]), (200, "image/jpeg"))
        self.assertEqual(anon.get(saved[0]["thumb_url"][:-6] + "xxxxx/").status_code, 404)
        self.assertEqual(self.state(uid)["state"], "committed")

    def test_first_photo_is_the_main_one_unless_told_otherwise(self):
        uid = self.draft()
        self.upload(uid, "a")
        self.upload(uid, "b")
        product = self.create({"draft": uid, "items": [{"upload": "a"}, {"upload": "b"}]})
        self.assertEqual([p["is_primary"] for p in self.photos_of(product["id"])], [True, False])

    def test_product_without_photos_still_saves(self):
        self.assertEqual(self.create()["photo_count"], 0)
        uid = self.draft()
        self.assertEqual(self.create({"draft": uid, "items": []}, name="另一個殼")["photo_count"], 0)

    def test_saving_again_with_the_same_draft_does_not_make_a_second_product(self):
        uid = self.draft()
        self.upload(uid, "a")
        payload = {"draft": uid, "items": [{"upload": "a"}]}
        first = self.create(payload)
        # 第一次其實成功了、回應沒收到 → 畫面拿同一份再送:回同一個商品
        again = self.create(payload, expect=200)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(Product.objects.filter(name=self.new_product["name"]).count(), 1)
        self.assertEqual(len(self.photos_of(first["id"])), 1)

    def test_another_form_holding_the_same_draft_is_not_mistaken_for_a_retry(self):
        # 兩個分頁都接回同一份草稿:第一個存好之後,第二個(品名不一樣)再存 ——
        # 不能回第一個建的商品、讓人以為自己的存好了;也不會多建
        uid = self.draft()
        self.upload(uid, "a")
        photos = {"draft": uid, "items": [{"upload": "a"}]}
        first = self.create(photos)
        body = self.create(photos, expect=400, name="另一個分頁打的品名")
        self.assertIn(first["name"], str(body))
        self.assertFalse(Product.objects.filter(name="另一個分頁打的品名").exists())
        self.assertEqual(len(self.photos_of(first["id"])), 1)

    def test_failed_save_leaves_no_photos_and_the_draft_can_be_retried(self):
        self.create()  # 先有一個同名的
        uid = self.draft()
        self.upload(uid, "a")
        payload = {"draft": uid, "items": [{"upload": "a"}]}
        self.create(payload, expect=409)  # 同名:商品沒建成
        self.assertEqual(ProductPhoto.objects.count(), 0)
        self.assertEqual(self.state(uid)["state"], "open")
        product = self.create(payload, name="換個名字就過了")
        self.assertEqual(len(self.photos_of(product["id"])), 1)

    def test_bad_photo_list_stops_the_product_from_being_created(self):
        uid = self.draft()
        self.upload(uid, "a")
        self.create({"draft": uid, "items": [{"upload": "not-mine"}]}, expect=400)
        self.assertFalse(Product.objects.filter(name=self.new_product["name"]).exists())
        many = [{"upload": "a"}] * (services.MAX_PHOTOS + 1)
        self.create({"draft": uid, "items": many}, expect=400)

    def test_cannot_save_while_a_photo_is_still_on_its_way(self):
        uid = self.draft()
        self.upload(uid, "a")
        _token, phone = self.pair(uid)
        self.assertEqual(phone.post("/api/v1/photo-pair/announce/", {"uid": "p1"}).status_code, 200)
        payload = {"draft": uid, "items": [{"upload": "a"}]}
        body = self.create(payload, expect=400)
        self.assertIn("尚未完成", body["detail"])
        self.assertFalse(Product.objects.filter(name=self.new_product["name"]).exists())
        # 取消沒傳完的那一張之後就能存;那一張晚到也進不來
        self.act(uid, "cancel-upload", uid="p1")
        product = self.create(payload)
        self.phone_upload(phone, "p1", expect=410)
        self.assertEqual(len(self.photos_of(product["id"])), 1)


class EditExistingTests(Base):
    def setUp(self):
        super().setUp()
        uid = self.draft()
        for key in ("a", "b", "c"):
            self.upload(uid, key)
        self.product = self.create({"draft": uid, "items": [
            {"upload": "a", "caption": "正面"}, {"upload": "b", "caption": "背面"},
            {"upload": "c", "caption": "接口"},
        ]})
        self.url = f"/api/v1/products/{self.product['id']}/"
        self.saved = self.photos_of(self.product["id"])

    def patch(self, photos, expect=200):
        # 畫面會帶「開表單時看到哪幾張」;測試沒特別指定就當作剛剛才開的表單
        photos = {"seen": [p["id"] for p in self.photos_of(self.product["id"])], **photos}
        resp = self.api.patch(self.url, {"photos": photos}, format="json")
        self.assertEqual(resp.status_code, expect, resp.content)
        return resp.json()

    def test_add_remove_reorder_and_change_the_main_photo(self):
        a, b, c = [p["id"] for p in self.saved]
        gone_file = ProductPhoto.objects.get(pk=b).image.name
        uid = self.draft(product=Product.objects.get(pk=self.product["id"]))
        self.upload(uid, "new")
        with self.captureOnCommitCallbacks(execute=True):
            answer = self.patch({"draft": uid, "items": [
                {"photo": c, "caption": "接口", "is_primary": True},
                {"upload": "new", "caption": "新包裝"},
                {"photo": a, "caption": "正面外觀"},
            ]})
        # 存檔的回應就是存完之後的樣子(不是存檔前查到的張數與主圖)
        self.assertEqual(answer["photo_count"], 3)
        self.assertEqual(services.read_file_token(answer["photo_thumb"].rstrip("/").split("/")[-1]), ("p", c, "t"))
        now = self.photos_of(self.product["id"])
        self.assertEqual([(p["caption"], p["is_primary"]) for p in now],
                         [("接口", True), ("新包裝", False), ("正面外觀", False)])
        self.assertFalse(ProductPhoto.objects.filter(pk=b).exists())
        self.assertFalse(default_storage.exists(gone_file))  # 移除的那一張檔案也刪了
        self.assertEqual(ProductPhoto.objects.filter(product_id=self.product["id"], is_primary=True).count(), 1)

    def test_lists_carry_the_main_photo_so_screens_can_show_a_thumbnail(self):
        # 商品清單 / 搜尋結果、庫存查詢:有照片的帶主圖的縮圖網址與張數;沒照片的是空的
        main = next(p for p in self.saved if p["is_primary"])
        plain = self.create(name="沒有照片的殼")
        listed = {p["id"]: p for p in self.api.get("/api/v1/products/?page_size=50").json()["results"]}
        self.assertEqual(listed[self.product["id"]]["photo_count"], 3)
        thumb = listed[self.product["id"]]["photo_thumb"]
        self.assertTrue(thumb)
        self.assertEqual((listed[plain["id"]]["photo_count"], listed[plain["id"]]["photo_thumb"]), (0, ""))
        # 縮圖網址打得開,而且就是主圖那一張的縮圖
        self.assertEqual(self.api.get(thumb).status_code, 200)
        self.assertEqual(services.read_file_token(thumb.rstrip("/").split("/")[-1]), ("p", main["id"], "t"))
        rows = {r["id"]: r for r in self.api.get("/api/v1/products/stock-matrix/?in_stock_only=false").json()["products"]}
        self.assertEqual(services.read_file_token(rows[self.product["id"]]["photo_thumb"].rstrip("/").split("/")[-1]),
                         ("p", main["id"], "t"))
        self.assertEqual(rows[plain["id"]]["photo_thumb"], "")

    def test_cancelling_the_edit_leaves_saved_photos_alone(self):
        uid = self.draft(product=Product.objects.get(pk=self.product["id"]))
        self.upload(uid, "new")
        self.act(uid, "cancel")
        self.assertEqual(self.photos_of(self.product["id"]), self.saved)
        # 取消之後這份作業不能再拿來存
        self.patch({"draft": uid, "items": [{"upload": "new"}]}, expect=400)
        self.assertEqual(self.photos_of(self.product["id"]), self.saved)

    def test_saving_other_fields_without_a_photo_list_keeps_the_photos(self):
        resp = self.api.patch(self.url, {"spec": "新規格"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.photos_of(self.product["id"]), self.saved)

    def test_someone_elses_newer_photo_is_not_wiped_by_a_stale_form(self):
        # 兩個人同時開同一個商品的表單。甲加了一張存好;乙的表單還是舊的,只改了說明就存 ——
        # 乙沒看過甲加的那一張,不能被當成「乙把它移除了」
        product = Product.objects.get(pk=self.product["id"])
        seen_by_both = [p["id"] for p in self.saved]
        a, b = self.draft(product=product), self.draft(product=product)
        self.upload(a, "from-a")
        self.patch({"draft": a, "seen": seen_by_both, "items": [
            *({"photo": pid} for pid in seen_by_both), {"upload": "from-a", "caption": "甲加的"},
        ]})
        after_a = self.photos_of(self.product["id"])
        self.assertEqual(len(after_a), 4)
        body = self.patch({"draft": b, "seen": seen_by_both, "items": [
            {"photo": pid, "caption": "乙改的說明"} for pid in seen_by_both
        ]}, expect=400)
        self.assertIn("被別人改過", str(body))
        self.assertEqual(self.photos_of(self.product["id"]), after_a)   # 一張都沒少,說明也沒被改
        # 沒帶「看到哪幾張」的存檔也不收(舊畫面 / 亂送的)
        resp = self.api.patch(self.url, {"photos": {"draft": b, "items": []}}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(self.photos_of(self.product["id"])), 4)
        # 乙重開表單(看到 4 張)就能存
        c = self.draft(product=product)
        self.patch({"draft": c, "items": [{"photo": p["id"], "caption": "乙改的說明"} for p in after_a]})
        self.assertEqual({p["caption"] for p in self.photos_of(self.product["id"])}, {"乙改的說明"})

    def test_photos_added_while_creating_a_product_cannot_be_put_on_an_existing_one(self):
        # 新增商品時加的照片(作業沒有綁商品):不能拿去存到既有的商品上 —— 那個商品原本的照片會被整批換掉
        loose = self.draft()
        self.upload(loose, "x")
        body = self.patch({"draft": loose, "items": [{"upload": "x"}]}, expect=400)
        self.assertIn("新增商品時加的", str(body))
        self.assertEqual([p["id"] for p in self.photos_of(self.product["id"])],
                         [p["id"] for p in self.saved])
        # 反過來:為既有商品開的作業,不能拿去新增另一個商品
        mine = self.draft(product=Product.objects.get(pk=self.product["id"]))
        self.upload(mine, "y")
        self.create({"draft": mine, "items": [{"upload": "y"}]}, expect=400, name="另一個新商品")
        self.assertFalse(Product.objects.filter(name="另一個新商品").exists())

    def test_a_draft_for_one_product_cannot_be_saved_onto_another(self):
        other = self.create(name="另一個商品")
        uid = self.draft(product=Product.objects.get(pk=other["id"]))
        self.upload(uid, "x")
        self.patch({"draft": uid, "items": [{"upload": "x"}]}, expect=400)
        # 別的商品的照片編號也不能混進來
        mine = self.draft(product=Product.objects.get(pk=other["id"]))
        resp = self.api.patch(f"/api/v1/products/{other['id']}/",
                              {"photos": {"draft": mine, "items": [{"photo": self.saved[0]["id"]}]}},
                              format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self.photos_of(self.product["id"]), self.saved)


class UploadTests(Base):
    def test_same_photo_sent_twice_is_one_photo(self):
        uid = self.draft()
        first = self.upload(uid, "a")
        again = self.upload(uid, "a")
        self.assertEqual(first["image_url"], again["image_url"])
        self.assertEqual(PhotoUpload.objects.filter(draft__uid=uid).count(), 1)

    def test_cancelling_the_whole_edit_deletes_what_was_uploaded(self):
        uid = self.draft()
        self.upload(uid, "a")
        name = PhotoUpload.objects.get(uid="a").image.name
        self.assertTrue(default_storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            self.act(uid, "cancel")
        self.assertFalse(default_storage.exists(name))  # 不等清理,當下就刪
        self.assertEqual(self.state(uid)["state"], "cancelled")

    def test_failed_photos_do_not_use_up_the_room_but_the_total_is_capped(self):
        uid = self.draft()
        bad = lambda: SimpleUploadedFile("x.jpg", b"not a picture", content_type="image/jpeg")  # noqa: E731
        for i in range(services.MAX_PENDING + 2):
            self.upload(uid, f"bad-{i}", expect=400, file=bad())
        self.upload(uid, "good")  # 失敗的不佔名額
        # 但一份作業總共記幾筆有上限(含失敗、取消的):擋有人一直灌
        with mock.patch.object(services, "MAX_ROWS", PhotoUpload.objects.filter(draft__uid=uid).count()):
            self.upload(uid, "one-more", expect=400)
            self.act(uid, "cancel-upload", uid="never-seen")
        self.assertFalse(PhotoUpload.objects.filter(uid="never-seen").exists())

    def test_retrying_a_failed_photo_makes_the_save_wait_for_it(self):
        uid = self.draft()
        bad = SimpleUploadedFile("x.jpg", b"not a picture", content_type="image/jpeg")
        self.upload(uid, "a", expect=400, file=bad)
        self.assertEqual(PhotoUpload.objects.get(uid="a").status, "failed")
        # 重試開始(圖片還在處理):狀態回到「上傳中」,商品這時候存不了(不會漏掉這一張)
        draft = PhotoDraft.objects.get(uid=uid)
        services.announce(draft, "a", PhotoUpload.Source.DESKTOP)
        self.assertEqual(PhotoUpload.objects.get(uid="a").status, "uploading")
        self.create({"draft": uid, "items": []}, expect=400)
        # 電腦正在儲存(停收)時不收重試
        self.upload(uid, "b", expect=400,
                    file=SimpleUploadedFile("x.jpg", b"nope", content_type="image/jpeg"))
        self.act(uid, "freeze")
        self.upload(uid, "b", expect=409)
        self.assertEqual(PhotoUpload.objects.get(uid="b").status, "failed")
        self.act(uid, "unfreeze")
        # 重試成功
        self.upload(uid, "a")
        self.assertEqual(PhotoUpload.objects.get(uid="a").status, "ready")
        # 已經傳好的那一張,同一個識別再送一次壞檔:不重新處理、不會被蓋成失敗
        self.upload(uid, "a", file=SimpleUploadedFile("x.jpg", b"nope", content_type="image/jpeg"))
        self.assertEqual(PhotoUpload.objects.get(uid="a").status, "ready")
        # 重試也要有名額:滿了就不收
        with mock.patch.object(services, "MAX_PENDING", 1):
            self.upload(uid, "b", expect=400)
        self.assertEqual(PhotoUpload.objects.get(uid="b").status, "failed")

    def test_cancelled_photo_does_not_come_back_when_its_upload_arrives_late(self):
        uid = self.draft()
        self.act(uid, "cancel-upload", uid="late")
        self.upload(uid, "late", expect=410)
        self.upload(uid, "kept")
        with self.captureOnCommitCallbacks(execute=True):
            self.act(uid, "cancel-upload", uid="kept")
        rows = {u["uid"]: u["status"] for u in self.state(uid)["uploads"]}
        self.assertEqual(rows, {"late": "cancelled", "kept": "cancelled"})
        self.create({"draft": uid, "items": [{"upload": "kept"}]}, expect=400)

    def test_a_file_that_is_not_a_photo_is_marked_failed_not_saved(self):
        uid = self.draft()
        body = self.upload(uid, "bad", expect=400,
                           file=SimpleUploadedFile("x.jpg", b"not a picture"))
        self.assertIn("不是照片", body["detail"])
        self.assertEqual(self.state(uid)["uploads"][0]["status"], "failed")
        self.create({"draft": uid, "items": [{"upload": "bad"}]}, expect=400)
        # 同一張換成好的檔重傳:就是那一格變成可用
        self.upload(uid, "bad")
        self.assertEqual(self.state(uid)["uploads"][0]["status"], "ready")

    def test_other_people_cannot_touch_my_draft(self):
        uid = self.draft()
        clerk = self.c.clerk
        self.assertEqual(clerk.get(f"/api/v1/photo-drafts/{uid}/").status_code, 410)
        self.upload(uid, "x", expect=410, client=clerk)
        other = Company("b", "乙通訊行", "乙")
        self.assertEqual(other.admin.get(f"/api/v1/photo-drafts/{uid}/").status_code, 410)
        # 別家公司的商品不能拿來開作業
        resp = other.admin.post("/api/v1/photo-drafts/", {"product": self.c.case.id}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            other.admin.get(f"/api/v1/product-photos/?product={self.c.case.id}").status_code, 404)

    def test_login_is_required_on_the_desktop_side(self):
        anon = APIClient()
        self.assertEqual(anon.post("/api/v1/photo-drafts/", {}, format="json").status_code, 401)
        self.assertEqual(anon.get("/api/v1/product-photos/?product=1").status_code, 401)


class PhonePairingTests(Base):
    def test_photo_taken_on_the_phone_shows_up_in_the_draft(self):
        uid = self.draft(label="透明防摔保護殼", spec="iPhone 15")
        self.assertEqual(self.state(uid)["pair"]["status"], "none")
        token = self.act(uid, "pair")["pair_token"]
        self.assertEqual(self.state(uid)["pair"]["status"], "waiting")
        phone = self.phone(token)
        seen = phone.post("/api/v1/photo-pair/claim/").json()
        # 手機只看得到:要放到哪一筆、自己傳了哪幾張
        self.assertEqual(set(seen), {"label", "spec", "sku", "frozen", "uploads"})
        self.assertEqual((seen["label"], seen["sku"]), ("透明防摔保護殼", ""))
        self.phone_upload(phone, "p1")
        state = self.state(uid)
        self.assertEqual((state["pair"]["status"], state["pair"]["received"]), ("connected", 1))
        self.assertEqual([(u["uid"], u["source"], u["status"]) for u in state["uploads"]],
                         [("p1", "phone", "ready")])
        # 電腦存檔:手機拍的跟電腦選的一起掛上去
        self.upload(uid, "d1")
        product = self.create({"draft": uid, "items": [{"upload": "p1"}, {"upload": "d1"}]})
        self.assertEqual(len(self.photos_of(product["id"])), 2)

    def test_phone_sees_the_new_name_when_the_draft_is_renamed(self):
        uid = self.draft(label="")
        _token, phone = self.pair(uid)
        self.api.patch(f"/api/v1/photo-drafts/{uid}/", {"label": "新名字", "spec": "黑"}, format="json")
        self.assertEqual(phone.get("/api/v1/photo-pair/state/").json()["label"], "新名字")

    def test_a_second_phone_cannot_take_over_but_the_same_phone_can_come_back(self):
        uid = self.draft()
        token, phone = self.pair(uid, device="phone-A")
        self.assertEqual(self.phone(token, "phone-B").post("/api/v1/photo-pair/claim/").status_code, 409)
        self.assertEqual(self.phone(token, "phone-B").post(
            "/api/v1/photo-pair/upload/", {"uid": "x", "file": picture()}, format="multipart"
        ).status_code, 409)
        # 同一支手機回應沒收到、再掃一次:接回原本的配對
        self.assertEqual(phone.post("/api/v1/photo-pair/claim/").status_code, 200)
        self.phone_upload(phone, "p1")

    def test_qr_code_nobody_scanned_in_time_stops_working(self):
        uid = self.draft()
        token = self.act(uid, "pair")["pair_token"]
        PhotoDraft.objects.filter(uid=uid).update(pair_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.state(uid)["pair"]["status"], "expired")
        resp = self.phone(token).post("/api/v1/photo-pair/claim/")
        self.assertEqual((resp.status_code, resp.json()["code"]), (410, "expired"))
        # 電腦按「重新產生」:新的可以用,舊的那張不行
        new_token, phone = self.pair(uid)
        self.assertNotEqual(new_token, token)
        self.assertEqual(self.phone(token).post("/api/v1/photo-pair/claim/").status_code, 410)
        self.phone_upload(phone, "p1")

    def test_refreshing_the_qr_code_disconnects_the_phone_that_was_connected(self):
        uid = self.draft()
        _old, old_phone = self.pair(uid, device="phone-A")
        self.pair(uid, device="phone-B")
        self.phone_upload(old_phone, "late", expect=410)

    def test_phone_that_went_quiet_is_disconnected(self):
        uid = self.draft()
        _token, phone = self.pair(uid)
        PhotoDraft.objects.filter(uid=uid).update(
            device_active_at=timezone.now() - services.DEVICE_IDLE - timedelta(seconds=5))
        self.assertEqual(self.state(uid)["pair"]["status"], "idle")
        self.phone_upload(phone, "p1", expect=410)
        # 一直開著狀態頁不算動作:不會因為輪詢就永遠連著
        uid2 = self.draft()
        _t, phone2 = self.pair(uid2)
        before = PhotoDraft.objects.get(uid=uid2).device_active_at
        phone2.get("/api/v1/photo-pair/state/")
        self.assertEqual(PhotoDraft.objects.get(uid=uid2).device_active_at, before)

    def test_old_phone_cannot_upload_after_the_desktop_moves_on(self):
        # 存完、取消、結束手機拍照:三種都一樣,那支手機再傳就是「已經失效」
        for ending in ("save", "cancel", "unpair"):
            with self.subTest(ending=ending):
                uid = self.draft()
                _token, phone = self.pair(uid)
                self.phone_upload(phone, "p1")
                if ending == "save":
                    self.create({"draft": uid, "items": [{"upload": "p1"}]}, name=f"商品 {ending}")
                else:
                    self.act(uid, ending)
                before = PhotoUpload.objects.count()
                self.phone_upload(phone, "p2", expect=410)
                self.assertEqual(phone.get("/api/v1/photo-pair/state/").status_code, 410)
                self.assertEqual(PhotoUpload.objects.count(), before)
        # 遲到的照片不會掛到下一筆商品:下一筆是另一份作業、另一張 QR Code
        self.assertEqual(ProductPhoto.objects.count(), 1)

    def test_while_the_desktop_is_saving_no_new_photo_is_taken_in(self):
        uid = self.draft()
        _token, phone = self.pair(uid)
        self.assertEqual(phone.post("/api/v1/photo-pair/announce/", {"uid": "on-its-way"}).status_code, 200)
        self.act(uid, "freeze")
        self.assertTrue(phone.get("/api/v1/photo-pair/state/").json()["frozen"])
        resp = phone.post("/api/v1/photo-pair/announce/", {"uid": "too-late"})
        self.assertEqual((resp.status_code, resp.json()["code"]), (409, "frozen"))
        self.phone_upload(phone, "too-late", expect=409)
        # 已經登記的那一張可以傳完
        self.phone_upload(phone, "on-its-way")
        # 存檔失敗、恢復編輯:又收得進來
        self.act(uid, "unfreeze")
        self.phone_upload(phone, "after")

    def test_phone_can_cancel_its_own_photo_and_finish(self):
        uid = self.draft()
        _token, phone = self.pair(uid)
        self.phone_upload(phone, "p1")
        self.assertEqual(phone.post("/api/v1/photo-pair/cancel/", {"uid": "p1"}).status_code, 200)
        self.assertEqual(phone.get("/api/v1/photo-pair/state/").json()["uploads"], [])
        self.phone_upload(phone, "p2")
        self.assertEqual(phone.post("/api/v1/photo-pair/finish/").status_code, 200)
        # 拍完了:手機不能再傳,已經收到的那一張還在,電腦照樣能存
        self.phone_upload(phone, "p3", expect=410)
        self.assertEqual(self.state(uid)["pair"]["status"], "none")
        product = self.create({"draft": uid, "items": [{"upload": "p2"}]})
        self.assertEqual(len(self.photos_of(product["id"])), 1)

    def test_phone_answers_are_never_kept_by_the_browser(self):
        # 手機問狀態的網址每次配對都一樣;瀏覽器預設會把 410 永久記住。
        # 沒擋的話:上一次配對結束時看到的「已結束」,會被拿來回答下一次配對
        uid = self.draft()
        _token, phone = self.pair(uid)
        alive = phone.get("/api/v1/photo-pair/state/")
        self.assertEqual(alive.status_code, 200)
        self.assertIn("no-store", alive["Cache-Control"])
        self.act(uid, "cancel")
        ended = phone.get("/api/v1/photo-pair/state/")
        self.assertEqual(ended.status_code, 410)
        self.assertIn("no-store", ended["Cache-Control"])
        # 電腦這邊問作業狀態也一樣
        self.assertIn("no-store", self.api.get(f"/api/v1/photo-drafts/{uid}/")["Cache-Control"])

    def test_old_phones_request_still_on_its_way_cannot_act_after_the_qr_is_refreshed(self):
        # 甲手機的請求已經驗過憑證、還在路上;這時電腦按「重新產生」、乙手機連上。
        # 甲那個請求接下來要做的事(登記、上傳、取消、完成)都不能成立,也不能把乙的配對結束掉
        uid = self.draft()
        _token_a, phone_a = self.pair(uid, "phone-A")
        self.phone_upload(phone_a, "a-1")
        draft = PhotoDraft.objects.get(uid=uid)
        pair_a = services.pair_of(draft)                      # 甲的請求驗過的那一次配對
        _token_b, phone_b = self.pair(uid, "phone-B")         # 電腦重新產生,乙連上
        for act in (
            lambda: services.announce(draft, "a-2", PhotoUpload.Source.PHONE, pair_a),
            lambda: services.add_upload(draft, "a-2", picture(), PhotoUpload.Source.PHONE, pair_a),
            lambda: services.cancel_upload(draft, "a-1", by=PhotoUpload.Source.PHONE, pair=pair_a),
        ):
            with self.assertRaises(PhotoRuleError) as caught:
                act()
            self.assertEqual(caught.exception.code, "gone")
        self.assertFalse(PhotoUpload.objects.filter(uid="a-2").exists())
        self.assertEqual(PhotoUpload.objects.get(uid="a-1").status, "ready")
        services.end_pair(draft, pair_a)                      # 甲晚到的「完成」
        self.assertFalse(services.still_paired(draft.pk, pair_a))
        self.assertEqual(self.state(uid)["pair"]["status"], "connected")   # 乙還連著
        self.phone_upload(phone_b, "b-1")
        # 乙自己按完成才結束
        self.assertEqual(phone_b.post("/api/v1/photo-pair/finish/").status_code, 200)
        self.assertEqual(self.state(uid)["pair"]["status"], "none")

    def test_removing_one_photo_on_the_phone_is_not_the_end_of_the_session(self):
        # 手機把還在傳的那一張移除,晚到的上傳被拒:要講「這一張取消了」,不是「這次配對結束了」
        uid = self.draft()
        _token, phone = self.pair(uid)
        phone.post("/api/v1/photo-pair/cancel/", {"uid": "x"}, format="json")
        late = phone.post("/api/v1/photo-pair/upload/", {"uid": "x", "file": picture()}, format="multipart")
        self.assertEqual((late.status_code, late.json()["code"]), (410, "cancelled"))
        self.assertEqual(phone.get("/api/v1/photo-pair/state/").status_code, 200)
        self.phone_upload(phone, "y")

    def test_phone_can_only_touch_the_photos_it_sent_itself(self):
        uid = self.draft()
        self.upload(uid, "from-desktop")
        _token, phone = self.pair(uid)
        # 手機拿電腦那一張的識別來取消 / 重傳:都不行,電腦那一張原封不動
        phone.post("/api/v1/photo-pair/cancel/", {"uid": "from-desktop"}, format="json")
        self.phone_upload(phone, "from-desktop", expect=400)
        row = PhotoUpload.objects.get(uid="from-desktop")
        self.assertEqual((row.status, row.source), ("ready", "desktop"))
        # 電腦可以拿掉手機傳來的
        self.phone_upload(phone, "from-phone")
        self.act(uid, "cancel-upload", uid="from-phone")
        self.assertEqual(PhotoUpload.objects.get(uid="from-phone").status, "cancelled")

    def test_pair_token_is_not_a_login(self):
        uid = self.draft()
        token, _phone = self.pair(uid)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}", HTTP_X_PAIR_TOKEN=token,
                      HTTP_X_PAIR_DEVICE="phone-A")
        self.assertEqual(c.get("/api/v1/products/").status_code, 401)
        self.assertEqual(c.get(f"/api/v1/photo-drafts/{uid}/").status_code, 401)
        # 沒帶手機識別、亂猜的憑證:都進不來
        self.assertEqual(self.phone("guess").get("/api/v1/photo-pair/state/").status_code, 410)
        self.assertEqual(self.phone(token, "").get("/api/v1/photo-pair/state/").status_code, 410)
        # 資料庫裡沒有存憑證本身
        self.assertNotIn(token, str(PhotoDraft.objects.filter(uid=uid).values().get()))

    def test_company_under_restore_blocks_the_phone_too(self):
        uid = self.draft()
        _token, phone = self.pair(uid)
        TenantMaintenance.objects.create(tenant=self.c.tenant, active=True)
        self.phone_upload(phone, "p1", expect=409)


class HousekeepingTests(Base):
    def test_cleanup_removes_abandoned_photos_but_never_saved_ones(self):
        kept_uid = self.draft()
        self.upload(kept_uid, "saved")
        self.upload(kept_uid, "left-out")
        left_file = PhotoUpload.objects.get(uid="left-out").image.name
        with self.captureOnCommitCallbacks(execute=True):
            product = self.create({"draft": kept_uid, "items": [{"upload": "saved"}]})
        saved_file = ProductPhoto.objects.get(product_id=product["id"]).image.name
        # 傳上來、最後沒放進清單的那一張:商品一存好就刪,不等清理
        self.assertFalse(default_storage.exists(left_file))
        self.assertTrue(default_storage.exists(saved_file))
        abandoned = self.draft()
        self.upload(abandoned, "x")
        abandoned_file = PhotoUpload.objects.get(uid="x").image.name
        active = self.draft()
        self.upload(active, "y")

        later = timezone.now() + services.CLOSED_KEEP + timedelta(minutes=5)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.cleanup(later), 1)  # 只清存完的那一份
        self.assertTrue(default_storage.exists(saved_file))
        self.assertTrue(default_storage.exists(abandoned_file))  # 還沒放到過期

        much_later = timezone.now() + services.DRAFT_TTL + timedelta(minutes=5)
        PhotoDraft.objects.filter(uid=active).update(updated_at=much_later)  # 這一份還在用
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.cleanup(much_later), 1)
        self.assertFalse(default_storage.exists(abandoned_file))
        self.assertTrue(PhotoDraft.objects.filter(uid=active).exists())
        self.assertTrue(default_storage.exists(saved_file))
        self.assertEqual(len(self.photos_of(product["id"])), 1)

    def test_old_drafts_are_swept_when_someone_starts_a_new_one(self):
        # 沒有另外排程:有人開新的照片作業時順手清舊的
        old = self.draft()
        self.upload(old, "x")
        old_file = PhotoUpload.objects.get(uid="x").image.name
        long_ago = timezone.now() - services.DRAFT_TTL - timedelta(hours=1)
        PhotoDraft.objects.filter(uid=old).update(updated_at=long_ago)
        with self.captureOnCommitCallbacks(execute=True):
            fresh = self.draft()
        self.assertFalse(PhotoDraft.objects.filter(uid=old).exists())
        self.assertFalse(default_storage.exists(old_file))
        self.assertTrue(PhotoDraft.objects.filter(uid=fresh).exists())

    def test_backup_list_knows_about_the_photo_tables(self):
        check_registry()

    def test_deleting_a_user_keeps_the_draft_rows_valid(self):
        uid = self.draft()
        get_user_model().objects.filter(pk=self.c.admin_user.pk).delete()
        self.assertIsNone(PhotoDraft.objects.get(uid=uid).created_by)


@override_settings(MEDIA_ROOT=MEDIA)
class OneAtATimeTests(TransactionTestCase):
    """處理圖片的那一兩秒握著作業的鎖:這段時間重新配對、取消、存檔、同一張的另一次傳都得等它做完,
    不會交錯。這要兩條資料庫連線才測得出來。"""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL")
        self.c = Company("a", "甲通訊行", "甲")
        resp = self.c.admin.post("/api/v1/photo-drafts/", {}, format="json")
        self.draft = PhotoDraft.objects.get(uid=resp.json()["uid"])

    def in_thread(self, fn):
        box = {}

        def run():
            try:
                box["value"] = fn()
            except Exception as exc:   # noqa: BLE001 - 測試要拿到任何一種失敗
                box["error"] = exc
            finally:
                connections.close_all()

        t = threading.Thread(target=run)
        t.start()
        return t, box

    def test_nothing_cuts_in_while_a_photo_is_being_processed(self):
        entered, go = threading.Event(), threading.Event()
        real = imaging.process

        def slow(fileobj):
            entered.set()
            self.assertTrue(go.wait(10))
            return real(fileobj)

        with mock.patch.object(services.imaging, "process", side_effect=slow):
            upload, up_box = self.in_thread(
                lambda: services.add_upload(self.draft, "a", picture(), PhotoUpload.Source.DESKTOP))
            self.assertTrue(entered.wait(10))
            # 這時候:電腦按「重新產生」、整份取消、同一張再傳一次壞檔,都要等
            pair, pair_box = self.in_thread(lambda: services.start_pair(self.draft))
            again, again_box = self.in_thread(lambda: services.add_upload(
                self.draft, "a", SimpleUploadedFile("x.jpg", b"nope"), PhotoUpload.Source.DESKTOP))
            pair.join(0.6)
            again.join(0.1)
            self.assertTrue(pair.is_alive() and again.is_alive())    # 都還在等
            self.assertFalse(PhotoUpload.objects.filter(uid="a", status="ready").exists())
            go.set()
            for t in (upload, pair, again):
                t.join(10)
        self.assertNotIn("error", up_box, up_box.get("error"))
        self.assertNotIn("error", pair_box, pair_box.get("error"))
        # 同一張的另一次(壞檔)是等前一次做完才進來的:看到已經傳好,不重新處理、不會蓋成失敗
        self.assertNotIn("error", again_box, again_box.get("error"))
        self.assertEqual(PhotoUpload.objects.get(uid="a").status, "ready")
        self.assertEqual(PhotoUpload.objects.filter(draft=self.draft).count(), 1)
