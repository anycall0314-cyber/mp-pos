"""舊會員整批帶進來:一位建一位 MP 會員並對照(owner 2026-10-09)。全部是假資料。"""
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import Category, Product
from apps.legacy import mapping
from apps.legacy.models import LegacyMappingLog, LegacyMember, MapStatus
from apps.parties.models import Member
from apps.sales.models import LegacyPurchase

from .archive_builder import ArchiveBuilder, doc, line
from .test_legacy_history import NEWER, OLDER, _Base


def people(b: ArchiveBuilder):
    """五位舊會員:兩位共用電話、一位沒電話、一位只有很久以前的消費。"""
    older, newer = b.batch(*OLDER), b.batch(*NEWER)

    def bought(batch, member, day, no):
        b.period(batch, member, [doc("湳雅店", "E11", no, day, [line("A1", "保貼", "1", "300", 300)])])

    bought(newer, b.member("001", "王小明", "0912-345-678"), "2025-03-01", "1140301001")
    bought(newer, b.member("002", "王太太", "0912345678"), "2024-06-01", "1130601001")     # 跟王小明同一支電話
    bought(newer, b.member("003", "沒電話", ""), "2025-01-05", "1140105001")
    bought(older, b.member("004", "很久沒來", "0933000222"), "2018-05-05", "1070505001")
    bought(newer, b.member("005", "林已建", "0955000111"), "2026-02-02", "1150202001")


class BringInTests(_Base):
    def setUp(self):
        super().setUp()
        self.run_import(self.build(people))

    def by_old_id(self, tenant=None):
        return {lm.source_member_id: lm for lm in
                LegacyMember.objects.filter(tenant=tenant or self.a).select_related("member")}

    def test_each_old_member_becomes_one_member(self):
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual(r, {"created": 5, "linked": 0, "no_phone": 1, "left": 0})
        old = self.by_old_id()
        self.assertEqual({lm.status for lm in old.values()}, {MapStatus.CONFIRMED})
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 5)
        wang = old["001"].member
        self.assertEqual((wang.name, wang.phone), ("王小明", "0912345678"))     # 連字號拿掉:店員是打數字找人
        self.assertEqual(old["001"].phone_raw, "0912-345-678")                   # 舊資料那一邊的原文不動
        self.assertIn("整批帶入", wang.note)
        self.assertTrue(wang.code.startswith("M-"))
        # 同一支電話的兩位各建各的,不合併
        self.assertNotEqual(old["001"].member_id, old["002"].member_id)
        self.assertEqual(old["003"].member.phone, "")
        self.assertEqual(LegacyMappingLog.objects.filter(tenant=self.a, note="整批帶入", action="confirm").count(), 5)
        self.assertEqual(old["001"].confirmed_by, self.boss)

    def test_the_trial_run_writes_nothing_and_gives_the_same_numbers(self):
        Member(tenant=self.a, name="林已建", phone="0955-000-111").save()
        trial = mapping.bring_in_members(self.a, self.boss)
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 1)
        self.assertEqual(LegacyMember.objects.filter(tenant=self.a, status=MapStatus.CONFIRMED).count(), 0)
        self.assertEqual(LegacyMappingLog.objects.count(), 0)
        self.assertEqual(mapping.bring_in_members(self.a, self.boss, write=True), trial)
        self.assertEqual(trial, {"created": 4, "linked": 1, "no_phone": 1, "left": 0})

    def test_someone_already_in_the_new_system_is_linked_not_duplicated(self):
        """電話與姓名都一樣、只有一位、還沒對照 → 連過去;只有電話一樣的另外建。"""
        lin = Member(tenant=self.a, name="林已建", phone="0955-000-111")
        lin.save()
        other = Member(tenant=self.a, name="王先生", phone="0912345678")      # 同電話、不同姓名
        other.save()
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual((r["created"], r["linked"]), (4, 1))
        old = self.by_old_id()
        self.assertEqual((old["005"].member_id, old["005"].method), (lin.pk, "phone"))
        self.assertNotIn(other.pk, {lm.member_id for lm in old.values()})
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 6)

    def test_two_old_records_of_the_same_person_do_not_share_one_member(self):
        """舊系統裡同名同電話的有兩筆、新系統有一位:第一筆連過去,第二筆另外建(一對一,不合併)。"""
        LegacyMember.objects.filter(tenant=self.a, source_member_id="004").update(
            name_raw="林已建", phone_raw="0955000111", phone_digits="0955000111")
        lin = Member(tenant=self.a, name="林已建", phone="0955000111")
        lin.save()
        trial = mapping.bring_in_members(self.a, self.boss)
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual(r, trial)
        self.assertEqual((r["created"], r["linked"]), (4, 1))
        old = self.by_old_id()
        self.assertEqual(sorted(k for k, lm in old.items() if lm.member_id == lin.pk), ["004"])
        self.assertNotEqual(old["005"].member_id, lin.pk)

    def test_two_people_with_the_same_name_and_phone_are_not_guessed(self):
        """新系統裡同電話同姓名的有兩位:不猜是哪一位,另外建。"""
        for _ in range(2):
            Member(tenant=self.a, name="林已建", phone="0955000111").save()
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual((r["created"], r["linked"]), (5, 0))

    def test_two_with_the_same_name_and_phone_are_not_guessed_even_if_one_is_already_linked(self):
        """複審抓到的:新系統有兩位同名同電話,其中一位已經對照到別的舊會員 —— 不能把另一位當成「唯一的一位」。"""
        first = Member(tenant=self.a, name="林已建", phone="0955000111")
        first.save()
        second = Member(tenant=self.a, name="林已建", phone="0955-000-111")
        second.save()
        mapping.link_member(self.by_old_id()["004"], first, self.boss)
        trial = mapping.bring_in_members(self.a, self.boss)
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual(r, trial)
        self.assertEqual((r["created"], r["linked"]), (4, 0))
        self.assertNotIn(self.by_old_id()["005"].member_id, (first.pk, second.pk))

    def test_a_member_already_linked_is_not_used_again(self):
        """新系統那一位已經對照到別的舊會員:這一個舊會員另外建。"""
        lin = Member(tenant=self.a, name="王小明", phone="0912345678")
        lin.save()
        mapping.link_member(self.by_old_id()["004"], lin, self.boss)
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual((r["created"], r["linked"], r["left"]), (4, 0, 0))
        self.assertNotEqual(self.by_old_id()["001"].member_id, lin.pk)

    def test_a_phone_with_other_words_in_it_is_kept_as_written(self):
        LegacyMember.objects.filter(tenant=self.a, source_member_id="003").update(
            phone_raw=" (02) 2345-6789 太太 ", phone_digits="0223456789")
        LegacyMember.objects.filter(tenant=self.a, source_member_id="004").update(
            phone_raw="(03) 555 1234", phone_digits="035551234")
        mapping.bring_in_members(self.a, self.boss, write=True)
        old = self.by_old_id()
        self.assertEqual(old["003"].member.phone, "(02) 2345-6789 太太")
        self.assertEqual(old["004"].member.phone, "035551234")

    def test_creating_one_by_hand_still_keeps_the_phone_as_written(self):
        _lm, member = mapping.create_member_from_legacy(self.by_old_id()["001"], self.boss)
        self.assertEqual(member.phone, "0912-345-678")
        self.assertNotIn("整批帶入", member.note)

    def test_running_it_again_changes_nothing(self):
        mapping.bring_in_members(self.a, self.boss, write=True)
        r = mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual(r, {"created": 0, "linked": 0, "no_phone": 0, "left": 0})
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 5)

    def test_only_recent_or_only_with_a_phone(self):
        r = mapping.bring_in_members(self.a, self.boss, since=date(2024, 1, 1), require_phone=True, write=True)
        self.assertEqual(r, {"created": 3, "linked": 0, "no_phone": 0, "left": 2})
        old = self.by_old_id()
        self.assertEqual({k for k, lm in old.items() if lm.member_id}, {"001", "002", "005"})
        # 之後再把剩下的帶進來
        self.assertEqual(mapping.bring_in_members(self.a, self.boss, write=True)["created"], 2)

    def test_another_company_is_untouched(self):
        self.run_import(self.build(people), tenant=self.b)
        Member(tenant=self.b, name="林已建", phone="0955000111").save()
        mapping.bring_in_members(self.a, self.boss, write=True)
        self.assertEqual(Member.objects.filter(tenant=self.b).count(), 1)
        self.assertEqual(LegacyMember.objects.filter(tenant=self.b, status=MapStatus.CONFIRMED).count(), 0)
        self.assertEqual({m.tenant_id for m in Member.objects.filter(legacy_members__tenant=self.a)}, {self.a.id})

    def test_the_old_history_shows_on_the_member_page(self):
        mapping.bring_in_members(self.a, self.boss, write=True)
        wang = self.by_old_id()["001"].member
        r = self.client_for(self.clerk).get("/api/v1/legacy/history/", {"member": wang.id})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["summary"]["documents"], 1)
        self.assertEqual(r.json()["summary"]["linked_legacy_members"], ["001"])
        found = self.client_for(self.clerk).get("/api/v1/members/", {"search": "0912345678"}).json()["results"]
        self.assertEqual(sorted(m["name"] for m in found), ["王太太", "王小明"])       # 同一支電話查到兩位,看姓名挑


class TakeBackTests(_Base):
    def setUp(self):
        super().setUp()
        self.run_import(self.build(people))
        self.lin = Member(tenant=self.a, name="林已建", phone="0955000111")
        self.lin.save()
        mapping.bring_in_members(self.a, self.boss, write=True)
        self.old = {lm.source_member_id: lm for lm in LegacyMember.objects.filter(tenant=self.a)}

    def test_take_back_removes_what_it_created_and_keeps_who_was_there(self):
        trial = mapping.take_back_members(self.a, self.boss)
        self.assertEqual(trial, {"removed": 4, "unlinked": 1, "kept": 0})
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 5)             # 試算不動
        self.assertEqual(mapping.take_back_members(self.a, self.boss, write=True), trial)
        self.assertEqual(list(Member.objects.filter(tenant=self.a)), [self.lin])      # 原本就有的還在
        self.assertEqual(LegacyMember.objects.filter(tenant=self.a, status=MapStatus.CONFIRMED).count(), 0)
        self.assertEqual(mapping.take_back_members(self.a, self.boss, write=True), {"removed": 0, "unlinked": 0, "kept": 0})
        # 收回之後可以再帶一次
        self.assertEqual(mapping.bring_in_members(self.a, self.boss, write=True)["created"], 4)

    def test_a_member_that_was_used_is_left_alone(self):
        used = self.old["001"].member
        category = Category.objects.create(tenant=self.a, code="LC", name="皮套")
        product = Product.objects.create(tenant=self.a, category=category, name="皮套", requires_serial=False)
        LegacyPurchase.objects.create(tenant=self.a, member=used, product=product, qty=1, unit_price=100,
                                      doc_date=date(2026, 10, 9))
        r = mapping.take_back_members(self.a, self.boss, write=True)
        self.assertEqual(r, {"removed": 3, "unlinked": 1, "kept": 1})
        self.assertTrue(Member.objects.filter(pk=used.pk).exists())
        self.old["001"].refresh_from_db()
        self.assertEqual((self.old["001"].status, self.old["001"].member_id), (MapStatus.CONFIRMED, used.pk))

    def test_links_made_by_hand_are_not_taken_back(self):
        """收回只動整批帶入的:人自己按「建立會員 / 對照」的不算。"""
        mapping.take_back_members(self.a, self.boss, write=True)
        _lm, by_hand = mapping.create_member_from_legacy(self.old["003"], self.boss)
        mapping.link_member(self.old["004"], self.lin, self.boss)
        self.assertEqual(mapping.take_back_members(self.a, self.boss, write=True), {"removed": 0, "unlinked": 0, "kept": 0})
        self.assertTrue(Member.objects.filter(pk=by_hand.pk).exists())

    def test_a_link_undone_and_made_again_by_hand_to_the_same_member_is_not_taken_back(self):
        """複審抓到的:整批帶入之後人解除、又自己連回同一位 —— 現在這個對照是人做的。"""
        again = self.old["002"]
        member = again.member
        mapping.unlink_member(again, self.boss)
        mapping.link_member(again, member, self.boss)
        r = mapping.take_back_members(self.a, self.boss, write=True)
        again.refresh_from_db()
        self.assertEqual((again.status, again.member_id), (MapStatus.CONFIRMED, member.pk))
        self.assertTrue(Member.objects.filter(pk=member.pk).exists())
        self.assertEqual(r, {"removed": 3, "unlinked": 1, "kept": 0})

    def test_a_member_someone_linked_another_old_record_to_is_left_alone(self):
        """複審抓到的:整批建的會員,人事後又把別的舊會員連到他 —— 試算與實際都要留著,不能實際跑才出錯。"""
        keep = self.old["001"].member
        other = self.old["002"]
        orphan = other.member
        mapping.unlink_member(other, self.boss)
        mapping.link_member(other, keep, self.boss)
        trial = mapping.take_back_members(self.a, self.boss)
        self.assertEqual(trial["kept"], 1)
        self.assertEqual(mapping.take_back_members(self.a, self.boss, write=True), trial)
        self.assertTrue(Member.objects.filter(pk=keep.pk).exists())
        self.assertEqual(LegacyMember.objects.filter(tenant=self.a, member=keep).count(), 2)
        self.assertTrue(Member.objects.filter(pk=orphan.pk).exists())     # 那一位已經不歸整批帶入管

    def test_a_link_changed_by_hand_afterwards_is_not_taken_back(self):
        moved = self.old["002"]
        was = moved.member_id
        mapping.unlink_member(moved, self.boss)
        mapping.link_member(moved, self.lin, self.boss)
        r = mapping.take_back_members(self.a, self.boss, write=True)
        moved.refresh_from_db()
        self.assertEqual((moved.status, moved.member_id), (MapStatus.CONFIRMED, self.lin.pk))
        self.assertTrue(Member.objects.filter(pk=was).exists())      # 那位當初整批建的會員已經不歸這次管
        self.assertEqual(r["removed"], 3)


class CommandTests(_Base):
    def setUp(self):
        super().setUp()
        self.run_import(self.build(people))

    def run_it(self, *args):
        out = StringIO()
        call_command("bring_in_legacy_members", *args, stdout=out)
        return out.getvalue()

    def test_trial_then_confirm_then_undo(self):
        text = self.run_it("--tenant", "a")
        self.assertIn("試算", text)
        self.assertIn("新建會員並對照 5 位(其中沒有電話的 1 位)", text)
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 0)
        self.assertIn("寫入", self.run_it("--tenant", "a", "--since", "2024-01-01", "--require-phone", "--confirm"))
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 3)
        self.assertIn("已經對照 3 位", self.run_it("--tenant", "a"))
        self.assertIn("沒被用過的會員 3 位", self.run_it("--tenant", "a", "--undo"))
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 3)             # 收回也要 --confirm
        self.run_it("--tenant", "a", "--undo", "--confirm")
        self.assertEqual(Member.objects.filter(tenant=self.a).count(), 0)

    def test_bad_arguments(self):
        for args in (["--tenant", "沒有這家"], ["--tenant", "a", "--since", "2024/01/01"],
                     ["--tenant", "a", "--undo", "--since", "2024-01-01"], ["--tenant", "a", "--undo", "--require-phone"]):
            with self.subTest(args=args):
                with self.assertRaises(CommandError):
                    self.run_it(*args)
        with self.assertRaises(CommandError):
            self.run_it("--confirm")                                                  # 一定要指名公司
