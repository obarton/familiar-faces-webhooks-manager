import json
import secrets
import uuid
from django.db import models


class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class WebhookEndpoint(BaseModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=24, unique=True, editable=False)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            for _ in range(5):
                candidate = secrets.token_urlsafe(9)  # 12 URL-safe chars
                if not WebhookEndpoint.objects.filter(slug=candidate).exists():
                    self.slug = candidate
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class WebhookEvent(BaseModel):
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name='events'
    )
    method = models.CharField(max_length=10)
    headers = models.JSONField(default=dict)
    body = models.TextField(blank=True, default='')
    query_params = models.JSONField(default=dict)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    sheet_tag = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['endpoint', '-created_at']),
        ]

    def __str__(self):
        return f"{self.method} → {self.endpoint.name} @ {self.created_at}"

    @property
    def body_size(self):
        return len(self.body.encode('utf-8'))

    @property
    def body_size_display(self):
        size = self.body_size
        if size < 1024:
            return f"{size} B"
        return f"{size / 1024:.1f} KB"

    @property
    def is_json(self):
        ct = self.headers.get('Content-Type', self.headers.get('content-type', ''))
        return 'json' in ct.lower()

    @property
    def preview_headers(self):
        return list(self.headers.items())[:3]
