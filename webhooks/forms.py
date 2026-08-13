from django import forms
from .models import WebhookEndpoint


class WebhookEndpointForm(forms.ModelForm):
    class Meta:
        model = WebhookEndpoint
        fields = ['name', 'description', 'forward_enabled', 'forward_url']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'autofocus': True,
                'placeholder': 'e.g. GitHub Events',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Optional description',
            }),
            'forward_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'forward_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com/webhook',
            }),
        }
