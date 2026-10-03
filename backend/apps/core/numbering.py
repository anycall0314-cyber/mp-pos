"""單號取號的共用小工具。"""


def last_doc_seq(model, tenant, prefix):
    """這家公司這種單據「已用到幾號」。

    = 最後一張單的流水號,與 `DocNumberFloor` 記的下限取大者。下限是資料還原時
    留下的:還原到較早的備份後,備份之後開過、已經給過客人的號碼不能再用一次。
    """
    from apps.tenants.models import DocNumberFloor

    last = model.objects.filter(tenant=tenant).order_by("-id").first()
    seq = 0
    if last and last.no:
        try:
            seq = int(last.no.split("-")[-1])
        except (ValueError, IndexError):
            seq = 0
    floor = (
        DocNumberFloor.objects.filter(tenant=tenant, prefix=prefix)
        .values_list("floor", flat=True)
        .first()
    )
    return max(seq, floor or 0)
