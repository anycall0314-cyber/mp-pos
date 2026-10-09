"""只有管理員拿得到、送得進來的欄位(公司實際拿的佣金、之後的實際成本)。

owner 2026-10-09:門市與管理員看到的佣金 / 成本不一樣。**擋在伺服器**:店員的回應裡根本沒有這些欄位,
不是畫面上藏起來(畫面藏的話,打開瀏覽器的開發工具就看得到)。

用法:序列化器繼承 `ManagerOnlyFieldsMixin`(放在繼承清單最前面),列出 `manager_only_fields`。
沒有帶 request 的序列化器(程式內部自己用的)一律當成不是管理員 —— 寧可少給。
"""


class ManagerOnlyFieldsMixin:
    manager_only_fields: tuple = ()

    def _for_a_manager(self) -> bool:
        from apps.tenants.permissions import is_tenant_admin

        request = self.context.get("request")
        return request is not None and is_tenant_admin(getattr(request, "user", None))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._for_a_manager():
            for name in self.manager_only_fields:
                data.pop(name, None)
        return data

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        if not self._for_a_manager():
            # 不是管理員送來的值不算數(當成沒送:新增時是空的,修改時不動原本的)
            for name in self.manager_only_fields:
                values.pop(name, None)
        return values
