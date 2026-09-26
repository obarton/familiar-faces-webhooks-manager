from django.contrib import admin
from .models import EventTag, WebhookEndpoint, WebhookEvent


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'forward_enabled', 'created_at']
    list_filter = ['is_active', 'forward_enabled']
    search_fields = ['name', 'slug']
    readonly_fields = ['id', 'slug', 'created_at', 'updated_at']


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ['endpoint', 'method', 'source_ip', 'created_at']
    list_filter = ['endpoint', 'method']
    readonly_fields = ['id', 'endpoint', 'method', 'headers', 'body',
                       'query_params', 'source_ip', 'forward_status',
                       'forwarded_at', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False


@admin.register(EventTag)
class EventTagAdmin(admin.ModelAdmin):
    list_display = ['city', 'event_date', 'tag', 'updated_at']
    list_filter = ['city']
    search_fields = ['city', 'tag']
    ordering = ['-event_date', 'city']
    readonly_fields = ['id', 'created_at', 'updated_at']
