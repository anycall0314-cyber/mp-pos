from django.contrib import admin

from .models import CommandLog


@admin.register(CommandLog)
class CommandLogAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "intent_action", "source", "result_doc_type",
                    "result_doc_id", "created_at")
    list_filter = ("status", "intent_action", "source")
    search_fields = ("raw_input", "message")
    readonly_fields = ("parsed_intent", "proposal", "clarification", "created_at", "updated_at")
