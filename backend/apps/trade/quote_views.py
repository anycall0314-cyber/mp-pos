"""報價連結的那一頁(不用登入;網址裡那一串就是鑰匙)。內容在 `quote.py`。"""
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from apps.backup.jobs import in_maintenance

from . import quote
from .base import setting_of
from .models import TradePartner

# 頁面自己只有內嵌的樣式與一小段程式;不載入任何外面的東西
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def _reply(html: str, status: int = 200) -> HttpResponse:
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = CSP
    return response


@require_GET
def page(request, token: str):
    link = quote.find(token)
    if link is None or not link.is_on:
        return _reply(quote.closed_page("連結已關閉"), 404)
    partner, seller = link.partner, link.partner.tenant
    if not seller.is_active or partner.status == TradePartner.Status.BLOCKED or not setting_of(seller).is_open:
        return _reply(quote.closed_page("連結已關閉"), 404)
    if not quote.hit(link):
        return _reply(quote.closed_page("請稍後再看"), 429)
    if in_maintenance(seller):
        return _reply(quote.closed_page("維護中"), 503)
    return _reply(quote.render(seller, partner))
