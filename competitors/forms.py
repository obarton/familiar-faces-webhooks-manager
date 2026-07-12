from django import forms

from .models import CompetitorSource

URL_FIELDS = ['instagram_url', 'tiktok_url', 'youtube_url']


class CompetitorSourceForm(forms.ModelForm):
    class Meta:
        model = CompetitorSource
        fields = ['name', 'is_own_brand', 'instagram_url', 'tiktok_url', 'youtube_url', 'crawl_limit']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'autofocus': True,
                'placeholder': 'e.g. Acme Events',
            }),
            'is_own_brand': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'instagram_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://instagram.com/competitor',
            }),
            'tiktok_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://tiktok.com/@competitor',
            }),
            'youtube_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://youtube.com/@competitor',
            }),
            'crawl_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 200,
            }),
        }

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in URL_FIELDS):
            raise forms.ValidationError(
                'Enter at least one URL — Instagram, TikTok, or YouTube.'
            )
        return cleaned
