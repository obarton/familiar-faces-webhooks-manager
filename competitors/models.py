from django.db import models
from django.utils import timezone

# The tracker reuses the webhooks app's BaseModel (UUID pk + created_at/updated_at)
# so both platform surfaces share identical model conventions.
from webhooks.models import BaseModel

# A content item is considered "new" (badged in the dashboard) if we first saw it
# within this window. Tied to created_at, which is when refresh first stored it.
NEW_ITEM_WINDOW = timezone.timedelta(hours=48)


class Platform(models.TextChoices):
    WEBSITE = 'website', 'Website'
    INSTAGRAM = 'instagram', 'Instagram'
    TIKTOK = 'tiktok', 'TikTok'
    YOUTUBE = 'youtube', 'YouTube'


# Display metadata per platform (Bootstrap Icons class + label), shared by the
# source channel list and the content-item badge.
PLATFORM_META = {
    Platform.WEBSITE: {'label': 'Website', 'icon': 'bi-globe'},
    Platform.INSTAGRAM: {'label': 'Instagram', 'icon': 'bi-instagram'},
    Platform.TIKTOK: {'label': 'TikTok', 'icon': 'bi-tiktok'},
    Platform.YOUTUBE: {'label': 'YouTube', 'icon': 'bi-youtube'},
}


class CompetitorSource(BaseModel):
    """A tracked account and its channels (socials). Either a competitor or, when
    is_own_brand is set, one of our own brand accounts — both crawled the same way
    and shown side by side."""
    name = models.CharField(max_length=200)
    is_own_brand = models.BooleanField(
        default=False,
        help_text='Track this as one of your own brand accounts (analyzed alongside competitors).',
    )
    instagram_url = models.URLField(max_length=500, blank=True, default='')
    tiktok_url = models.URLField(max_length=500, blank=True, default='')
    youtube_url = models.URLField(max_length=500, blank=True, default='')
    is_active = models.BooleanField(default=True)
    crawl_limit = models.PositiveIntegerField(
        default=25,
        help_text='Max items per channel on each recurring refresh (Instagram/TikTok '
                  'posts, YouTube videos). The first refresh pulls deeper '
                  '(see COMPETITOR_BACKFILL_LIMIT).',
    )
    last_crawled_at = models.DateTimeField(null=True, blank=True)

    # Background refresh: the UI queues a refresh by flagging this; the
    # refresh_competitors worker crawls flagged/stale sources and writes status.
    refresh_requested = models.BooleanField(default=True)
    # First refresh of a new competitor pulls a deeper backfill, then recurring
    # refreshes use the smaller crawl_limit. Cleared after the first crawl.
    backfill_requested = models.BooleanField(default=True)

    # AI competitor analysis (Claude), generated on demand and cached here.
    ai_summary = models.TextField(blank=True, default='')
    ai_summary_generated_at = models.DateTimeField(null=True, blank=True)
    last_refresh_status = models.CharField(max_length=200, blank=True, default='')
    last_refresh_note = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_queued(self):
        return self.refresh_requested

    @property
    def item_count(self):
        return self.items.count()

    @property
    def role_label(self):
        return 'Your brand' if self.is_own_brand else 'Competitor'

    @property
    def channels(self):
        """Configured channels as display-ready dicts (platform, url, label, icon)."""
        out = []
        for platform, url in (
            (Platform.INSTAGRAM, self.instagram_url),
            (Platform.TIKTOK, self.tiktok_url),
            (Platform.YOUTUBE, self.youtube_url),
        ):
            if url:
                meta = PLATFORM_META[platform]
                out.append({
                    'platform': platform,
                    'url': url,
                    'label': meta['label'],
                    'icon': meta['icon'],
                })
        return out


class LandscapeReport(BaseModel):
    """The latest AI-generated competitive-landscape report (markdown) across all
    tracked accounts. Only the most recent is kept."""
    markdown = models.TextField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Landscape report {self.created_at:%Y-%m-%d %H:%M}'


class CompetitorContentItem(BaseModel):
    """A single piece of content discovered on one of a competitor's channels.

    Deduplicated per (source, url): re-crawls update the existing row rather than
    creating duplicates, so the "new items" count reflects genuinely new content.
    """
    source = models.ForeignKey(
        CompetitorSource, on_delete=models.CASCADE, related_name='items'
    )
    platform = models.CharField(
        max_length=20, choices=Platform.choices, default=Platform.WEBSITE
    )
    # Sub-type within a platform: 'post'/'reel' (IG), 'video' (TikTok/YouTube),
    # 'article' (website). Drives the FORMAT label. Blank falls back per platform.
    content_type = models.CharField(max_length=20, blank=True, default='')
    url = models.URLField(max_length=1000)
    title = models.CharField(max_length=500, blank=True, default='')
    description = models.TextField(blank=True, default='')
    summary = models.TextField(blank=True, default='')          # AI-generated
    keywords = models.JSONField(default=list, blank=True)        # AI-generated
    published_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'url'], name='unique_source_url'
            ),
        ]
        indexes = [
            models.Index(fields=['source', '-created_at']),
        ]

    def __str__(self):
        return self.title or self.url

    @property
    def is_new(self):
        return (timezone.now() - self.created_at) <= NEW_ITEM_WINDOW

    @property
    def display_title(self):
        return self.title or self.url

    @property
    def platform_icon(self):
        return PLATFORM_META.get(self.platform, PLATFORM_META[Platform.WEBSITE])['icon']

    @property
    def platform_label(self):
        return PLATFORM_META.get(self.platform, PLATFORM_META[Platform.WEBSITE])['label']

    @property
    def format_label(self):
        """Human FORMAT tag, e.g. 'Instagram Reel', 'TikTok Video', 'Article'."""
        if self.platform == Platform.INSTAGRAM:
            return 'Instagram Reel' if self.content_type == 'reel' else 'Instagram Post'
        if self.platform == Platform.TIKTOK:
            return 'TikTok Video'
        if self.platform == Platform.YOUTUBE:
            return 'YouTube Video'
        return 'Article'
