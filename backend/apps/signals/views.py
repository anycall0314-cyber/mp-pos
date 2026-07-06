from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import DemandAlert
from .serializers import DemandAlertSerializer


class DemandAlertViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """需求警示(唯讀)+ 重新計算。

    GET  /api/v1/signals/demand-alerts/              列出警示
    POST /api/v1/signals/demand-alerts/recompute/    依現有訊號重算商品需求警示
    POST /api/v1/signals/demand-alerts/{id}/ack/     標記已讀
    """

    serializer_class = DemandAlertSerializer
    filterset_fields = ["status", "direction", "authorized", "kind"]
    search_fields = ["subject_key"]
    ordering = ["-window_end", "-id"]

    def get_queryset(self):
        return DemandAlert.objects.for_tenant(self.request.tenant).select_related("product")

    @action(detail=False, methods=["post"])
    def recompute(self, request):
        alerts = services.compute_product_demand_alerts(request.tenant)
        return Response(
            {"created": len(alerts), "alerts": self.get_serializer(alerts, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        alert = self.get_object()
        alert.status = DemandAlert.Status.ACK
        alert.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(alert).data)
