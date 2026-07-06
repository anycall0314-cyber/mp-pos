from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import CommandLog
from .serializers import CommandCreateSerializer, CommandLogSerializer


class CommandViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """AI 指令入口。

    POST /api/v1/assistant/commands/           送出一句話 / 一張進貨單 → 回提案或追問
    POST /api/v1/assistant/commands/{id}/confirm/   確認提案 → 呼叫既有 service 過帳
    POST /api/v1/assistant/commands/{id}/reject/    放棄
    GET  /api/v1/assistant/commands/           歷史
    """

    serializer_class = CommandLogSerializer
    search_fields = ["raw_input", "intent_action", "message"]
    ordering = ["-id"]
    filterset_fields = ["status", "intent_action", "source"]

    def get_queryset(self):
        return CommandLog.objects.for_tenant(self.request.tenant)

    def create(self, request, *args, **kwargs):
        payload = CommandCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        cmd = services.interpret(
            tenant=request.tenant,
            raw_input=payload.validated_data["raw_input"],
            source=payload.validated_data["source"],
            user=user,
        )
        return Response(self.get_serializer(cmd).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        cmd = self.get_object()
        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        try:
            cmd = services.confirm(cmd, user=user)
        except services.CommandError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(cmd).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        cmd = self.get_object()
        if cmd.status in (CommandLog.Status.COMMITTED, CommandLog.Status.REJECTED):
            return Response({"detail": "此指令已結案"}, status=status.HTTP_400_BAD_REQUEST)
        cmd.status = CommandLog.Status.REJECTED
        cmd.message = "使用者已取消"
        cmd.save(update_fields=["status", "message", "updated_at"])
        return Response(self.get_serializer(cmd).data)
