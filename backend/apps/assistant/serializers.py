from rest_framework import serializers

from .models import CommandLog


class CommandLogSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)

    class Meta:
        model = CommandLog
        fields = [
            "id",
            "source",
            "source_label",
            "raw_input",
            "intent_action",
            "parsed_intent",
            "proposal",
            "clarification",
            "status",
            "status_label",
            "message",
            "result_doc_type",
            "result_doc_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CommandCreateSerializer(serializers.Serializer):
    raw_input = serializers.CharField()
    source = serializers.ChoiceField(
        choices=CommandLog.Source.choices,
        default=CommandLog.Source.NL_TEXT,
    )
