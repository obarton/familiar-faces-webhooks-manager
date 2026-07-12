from django.contrib import admin

from .models import CompetitorContentItem, CompetitorSource


@admin.register(CompetitorSource)
class CompetitorSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'instagram_url', 'tiktok_url', 'youtube_url',
                    'is_active', 'last_crawled_at', 'item_count')
    search_fields = ('name', 'instagram_url', 'tiktok_url', 'youtube_url')
    list_filter = ('is_active',)


@admin.register(CompetitorContentItem)
class CompetitorContentItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'platform', 'source', 'published_date', 'created_at')
    search_fields = ('title', 'url', 'summary')
    list_filter = ('platform', 'source')
    readonly_fields = ('created_at', 'updated_at')
