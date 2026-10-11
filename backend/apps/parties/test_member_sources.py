from datetime import date

from django.test import TestCase

from apps.backup.tests.factory import Company
from apps.inventory.models import StockBalance
from apps.parties.models import Customer, Member
from apps.sales.models import SalesOrder


class MemberSourcesTests(TestCase):
    def setUp(self):
        self.a = Company("sources-a", "甲店", "甲")
        self.b = Company("sources-b", "乙店", "乙")
        self.a.purchase(case_qty=30)
        self.source = Customer.objects.create(tenant=self.a.tenant, name="A 通路", kind="channel", tax_id="11111111")
        self.peer = Customer.objects.create(tenant=self.a.tenant, name="B 同業", kind="peer")

    def member(self, **extra):
        response = self.a.admin.post("/api/v1/members/", {"name": "乙公司", "kind": "company", "tax_id": "22222222", "contact": "林小姐", **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def default(self, customer):
        response = self.a.admin.post("/api/v1/customers/sales-default/", {"customer": customer}, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def sale(self, **extra):
        body = {"warehouse": self.a.wh.id, "tax_method": "untaxed", "sales_person": self.a.sales_person.id,
                "items": [{"product": self.a.case.id, "qty": 1, "unit_price": "390"}],
                "payments": [{"method": "cash", "amount": "390"}], **extra}
        return self.a.admin.post("/api/v1/sales-orders/", body, format="json")

    def test_company_member_identity_and_tax_id_search(self):
        member = self.member(default_source_mode="customer", default_customer=self.source.id)
        self.assertEqual(member["default_customer_detail"]["name"], "A 通路")
        results = self.a.admin.get("/api/v1/members/", {"search": "22222222"}).json()["results"]
        self.assertEqual([r["id"] for r in results], [member["id"]])
        self.assertEqual(results[0]["contact"], "林小姐")

    def test_direct_sale_and_default_source_do_not_change_amount_or_stock(self):
        direct = self.sale()
        self.assertEqual(direct.status_code, 201, direct.content)
        self.assertEqual((direct.json()["customer"], direct.json()["source_name"]), (None, "直客"))
        self.default(self.source.id)
        routed = self.sale()
        self.assertEqual(routed.status_code, 201, routed.content)
        self.assertEqual((routed.json()["customer"], routed.json()["source_name"]), (self.source.id, "A 通路"))
        self.assertEqual(routed.json()["total"], "390.00")
        self.assertEqual(StockBalance.objects.get(warehouse=self.a.wh, product=self.a.case).qty, 28)

    def test_member_inherits_sales_default_or_explicitly_selects_direct_or_source(self):
        self.default(self.source.id)
        inherited = self.member()
        direct = self.member(default_source_mode="direct")
        peer = self.member(default_source_mode="customer", default_customer=self.peer.id)
        for member, expected in [(inherited, self.source.id), (direct, None), (peer, self.peer.id)]:
            result = self.sale(member=member["id"])
            self.assertEqual(result.status_code, 201, result.content)
            self.assertEqual(result.json()["customer"], expected)

    def test_transaction_override_does_not_change_member_or_previous_sales(self):
        member = self.member(default_source_mode="customer", default_customer=self.source.id)
        first = self.sale(member=member["id"], customer=None).json()
        second = self.sale(member=member["id"], customer=self.peer.id).json()
        self.a.admin.patch(f'/api/v1/members/{member["id"]}/', {"default_source_mode": "direct"}, format="json")
        self.default(self.peer.id)
        self.source.name = "改名後通路"
        self.source.save(update_fields=["name"])
        self.assertEqual(self.a.admin.get(f'/api/v1/sales-orders/{first["id"]}/').json()["source_name"], "直客")
        self.assertEqual(self.a.admin.get(f'/api/v1/sales-orders/{second["id"]}/').json()["source_name"], "B 同業")

    def test_channel_tax_id_does_not_become_buyer_tax_id(self):
        member = self.member(default_source_mode="customer", default_customer=self.source.id)
        sale = self.sale(member=member["id"])
        self.assertEqual(sale.status_code, 201, sale.content)
        self.assertEqual(sale.json()["buyer_tax_id"], "")

    def test_new_sources_cannot_cross_company(self):
        foreign = self.b.customer.id
        member = self.a.admin.post("/api/v1/members/", {"name": "王先生", "default_source_mode": "customer", "default_customer": foreign}, format="json")
        self.assertEqual(member.status_code, 400)
        default = self.a.admin.post("/api/v1/customers/sales-default/", {"customer": foreign}, format="json")
        self.assertEqual(default.status_code, 400)
        self.assertEqual(self.sale(customer=foreign).status_code, 400)

    def test_only_manager_can_change_company_default_and_only_one_is_selected(self):
        self.assertEqual(self.a.clerk.post("/api/v1/customers/sales-default/", {"customer": self.source.id}, format="json").status_code, 403)
        self.default(self.source.id)
        self.default(self.peer.id)
        self.assertEqual(list(Customer.objects.filter(tenant=self.a.tenant, is_sales_default=True).values_list("id", flat=True)), [self.peer.id])
        self.default(None)
        self.assertIsNone(self.a.admin.get("/api/v1/customers/sales-default/").json()["customer"])

    def test_inactive_source_rejected_and_no_stock_deducted(self):
        member = self.member(default_source_mode="customer", default_customer=self.source.id)
        self.source.is_active = False
        self.source.save(update_fields=["is_active"])
        for extra in [{"customer": self.source.id}, {"member": member["id"]}]:
            self.assertEqual(self.sale(**extra).status_code, 400)
        self.assertEqual(StockBalance.objects.get(warehouse=self.a.wh, product=self.a.case).qty, 30)
        self.assertEqual(self.a.admin.post("/api/v1/customers/sales-default/", {"customer": self.source.id}, format="json").status_code, 400)

    def test_default_source_cannot_be_disabled_without_changing_default(self):
        self.default(self.source.id)
        response = self.a.admin.patch(f"/api/v1/customers/{self.source.id}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.a.admin.delete(f"/api/v1/customers/{self.source.id}/").status_code, 400)

    def test_existing_sales_keep_original_customer_and_no_source_snapshot(self):
        old = SalesOrder.objects.create(tenant=self.a.tenant, customer=self.a.customer, warehouse=self.a.wh)
        response = self.a.admin.get(f"/api/v1/sales-orders/{old.pk}/").json()
        self.assertEqual(response["source_name"], "")
        self.assertEqual(response["customer_name"], self.a.customer.name)

    def test_repair_uses_member_without_creating_another_customer(self):
        member = self.member(default_source_mode="customer", default_customer=self.source.id)
        count = Customer.objects.filter(tenant=self.a.tenant).count()
        response = self.a.admin.post("/api/v1/repair-orders/", {"member": member["id"], "warehouse": self.a.wh.id, "received_date": str(date.today()), "mode": "in_house", "unlock_method": "none", "host_model_name": "iPhone 17"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["customer_name"], "乙公司")
        self.assertEqual(response.json()["customer"], self.source.id)
        self.assertEqual(Customer.objects.filter(tenant=self.a.tenant).count(), count)
        other = self.a.admin.post("/api/v1/repair-orders/", {"member": self.member(default_source_mode="direct")["id"], "warehouse": self.a.wh.id, "received_date": str(date.today()), "mode": "in_house"}, format="json")
        self.assertEqual(other.status_code, 201, other.content)
        self.assertIsNone(other.json()["customer"])

    def test_member_repair_history_and_return_visit_use_recipient_phone(self):
        self.source.phone = "0912999999"
        self.source.save(update_fields=["phone"])
        for mode, source in [("direct", None), ("customer", self.source.id)]:
            with self.subTest(mode=mode):
                phone = "0900000001" if mode == "direct" else "0900000002"
                member = self.member(phone=phone, default_source_mode=mode, default_customer=source)
                body = {"member": member["id"], "warehouse": self.a.wh.id,
                        "received_date": str(date.today()), "mode": "in_house"}
                first = self.a.admin.post("/api/v1/repair-orders/", body, format="json")
                self.assertEqual(first.status_code, 201, first.content)
                history = self.a.admin.get("/api/v1/repair-orders/history-by-phone/", {"phone": phone})
                self.assertEqual([row["id"] for row in history.json()], [first.json()["id"]])
                followup = self.a.admin.post("/api/v1/repair-orders/", {
                    **body, "is_return_visit": True, "previous_repair_order": history.json()[0]["id"]
                }, format="json")
                self.assertEqual(followup.status_code, 201, followup.content)
                self.assertEqual(followup.json()["previous_repair_order"], first.json()["id"])
                self.assertEqual(followup.json()["member"], member["id"])
                # 通路的電話不是送修人的電話，不可查到會員維修單。
                self.assertNotIn(first.json()["id"], [row["id"] for row in self.a.admin.get(
                    "/api/v1/repair-orders/history-by-phone/", {"phone": self.source.phone}
                ).json()])

    def test_old_customer_repair_history_still_works(self):
        result = self.a.admin.post("/api/v1/repair-orders/", {
            "customer": self.a.customer.id, "warehouse": self.a.wh.id,
            "received_date": str(date.today()), "mode": "in_house"
        }, format="json")
        self.assertEqual(result.status_code, 201, result.content)
        history = self.a.admin.get("/api/v1/repair-orders/history-by-phone/", {"phone": self.a.customer.phone})
        self.assertEqual([row["id"] for row in history.json()], [result.json()["id"]])

    def test_repair_search_and_existing_inactive_member_edit(self):
        member = self.member(phone="0900000003", default_source_mode="direct")
        result = self.a.admin.post("/api/v1/repair-orders/", {
            "member": member["id"], "warehouse": self.a.wh.id,
            "received_date": str(date.today()), "mode": "in_house"
        }, format="json")
        self.assertEqual(result.status_code, 201, result.content)
        for query in [member["name"], member["phone"]]:
            rows = self.a.admin.get("/api/v1/repair-orders/", {"search": query}).json()["results"]
            self.assertEqual([row["id"] for row in rows], [result.json()["id"]])
        self.a.admin.patch(f'/api/v1/members/{member["id"]}/', {"is_active": False}, format="json")
        update = self.a.admin.patch(f'/api/v1/repair-orders/{result.json()["id"]}/', {
            "member": member["id"], "final_quote": "500"
        }, format="json")
        self.assertEqual(update.status_code, 200, update.content)
        new = self.a.admin.post("/api/v1/repair-orders/", {
            "member": member["id"], "warehouse": self.a.wh.id,
            "received_date": str(date.today()), "mode": "in_house"
        }, format="json")
        self.assertEqual(new.status_code, 400)
