from django import forms
from .models import EventTag, WebhookEndpoint


class WebhookEndpointForm(forms.ModelForm):
    class Meta:
        model = WebhookEndpoint
        fields = ['name', 'description']
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
        }


class EventTagForm(forms.ModelForm):
    class Meta:
        model = EventTag
        fields = ['city', 'event_date', 'tag']
        widgets = {
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'autofocus': True,
                'placeholder': 'e.g. San Francisco',
            }),
            # type=date needs the value formatted as YYYY-MM-DD so an existing
            # date pre-fills the input when editing.
            'event_date': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'},
                format='%Y-%m-%d',
            ),
            'tag': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. FAMILIAR_FACES_SF_07042026_PURCHASED',
            }),
        }
