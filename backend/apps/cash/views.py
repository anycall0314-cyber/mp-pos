from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import PettyExpense
from .serializers import PettyExpenseSerializer


class PettyExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = PettyExpenseSerializer
    search_fields = ["no", "payee", "note"]
    ordering_fields = ["doc_date", "amount", "created_at"]
    ordering = ["-doc_date", "-id"]
    filterset_fields = {
        "warehouse": ["exact"],
        "category": ["exact"],
        "payment_method": ["exact"],
        "is_void": ["exact"],
        "doc_date": ["exact", "gte", "lte"],
    }

    def get_queryset(self):
        return (
            PettyExpense.objects.for_tenant(self.request.tenant)
            .select_related("warehouse", "payment_method")
        )

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        obj = self.get_object()
        if obj.is_void:
            return Response(
                {"detail": "已作廢"}, status=status.HTTP_400_BAD_REQUEST
            )
        obj.is_void = True
        obj.save(update_fields=["is_void"])
        return Response(self.get_serializer(obj).data)
