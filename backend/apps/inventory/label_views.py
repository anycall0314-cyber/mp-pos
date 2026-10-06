"""標籤資料(規則在 `labels.py`)。

GET /labels/?po=進貨單編號
GET /labels/?serials=1,2,3
GET /labels/?product=商品編號&copies=張數
回 {"source", "labels": [每一張要印的內容], "notes": [要講出來的事]}

三種擇一。只讀;只看得到自己公司的(別家的編號跟不存在的一樣)。
門市範圍跟序號清單(`/serials/`)一樣不另外鎖:標籤上的東西(品名、售價、序號)庫存查詢本來就看得到。
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import labels as rules


def _int(raw):
    """編號 / 張數:只收一般的數字(全形數字、長到資料庫放不下的都不收,不然後面會出錯而不是好好講)。"""
    raw = (raw or "").strip()
    if not (raw.isascii() and raw.isdigit() and len(raw) <= 18):
        raise rules.LabelError("編號或張數的格式不對")
    return int(raw)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def label_data(request):
    q = request.query_params
    modes = [name for name in ("po", "serials", "product") if (q.get(name) or "").strip()]
    try:
        if len(modes) != 1:
            raise rules.LabelError("要印哪一張進貨單、哪幾台、或哪一個商品,擇一")
        if modes[0] == "po":
            source, labels, notes = rules.for_purchase_order(request.tenant, _int(q.get("po")))
        elif modes[0] == "serials":
            ids = [_int(part) for part in q.get("serials").split(",") if part.strip()]
            source, labels, notes = rules.for_serials(request.tenant, ids)
        else:
            source, labels, notes = rules.for_product(
                request.tenant, _int(q.get("product")), _int(q.get("copies") or "1"))
    except rules.LabelError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    # notes:要講給人知道的事(哪一行少印了幾台、哪一行的張數被壓到上限)
    return Response({"source": source, "labels": labels, "notes": notes})
