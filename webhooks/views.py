import json
import logging
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Subquery, OuterRef
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from .forms import WebhookEndpointForm
from .models import WebhookEndpoint, WebhookEvent

logger = logging.getLogger(__name__)


@login_required
def endpoint_list(request):
    count_sq = (
        WebhookEvent.objects
        .filter(endpoint=OuterRef('pk'))
        .values('endpoint')
        .annotate(c=Count('id'))
        .values('c')
    )
    endpoints = WebhookEndpoint.objects.annotate(
        event_count=Coalesce(Subquery(count_sq), 0)
    )
    return render(request, 'webhooks/endpoint_list.html', {'endpoints': endpoints})


@login_required
def endpoint_create(request):
    form = WebhookEndpointForm(request.POST or None)
    if form.is_valid():
        endpoint = form.save()
        messages.success(request, f'Endpoint "{endpoint.name}" created.')
        return redirect('webhooks:endpoint_detail', id=endpoint.id)
    return render(request, 'webhooks/endpoint_create.html', {'form': form})


@login_required
def endpoint_detail(request, id):
    endpoint = get_object_or_404(WebhookEndpoint, id=id)
    events = endpoint.events.all()[:50]
    receiver_url = request.build_absolute_uri(
        reverse('webhooks:receive_webhook', kwargs={'slug': endpoint.slug})
    )
    return render(request, 'webhooks/endpoint_detail.html', {
        'endpoint': endpoint,
        'events': events,
        'receiver_url': receiver_url,
    })


@login_required
def endpoint_delete(request, id):
    endpoint = get_object_or_404(WebhookEndpoint, id=id)
    if request.method == 'POST':
        name = endpoint.name
        endpoint.delete()
        messages.success(request, f'Endpoint "{name}" deleted.')
        return redirect('webhooks:endpoint_list')
    event_count = endpoint.events.count()
    return render(request, 'webhooks/endpoint_confirm_delete.html', {
        'endpoint': endpoint,
        'event_count': event_count,
    })


@login_required
def event_detail(request, id, event_id):
    endpoint = get_object_or_404(WebhookEndpoint, id=id)
    event = get_object_or_404(WebhookEvent, id=event_id, endpoint=endpoint)
    body_pretty = None
    if event.is_json:
        try:
            body_pretty = json.dumps(json.loads(event.body), indent=2)
        except Exception:
            pass
    content_type = (
        event.headers.get('Content-Type')
        or event.headers.get('content-type')
        or '—'
    )
    return render(request, 'webhooks/event_detail.html', {
        'endpoint': endpoint,
        'event': event,
        'body_pretty': body_pretty,
        'content_type': content_type,
    })


@login_required
def events_poll(request, id):
    endpoint = get_object_or_404(WebhookEndpoint, id=id)
    since_str = request.GET.get('since')
    qs = WebhookEvent.objects.filter(endpoint=endpoint)
    if since_str:
        since_dt = parse_datetime(since_str)
        if since_dt:
            qs = qs.filter(created_at__gt=since_dt)
    events = qs.order_by('-created_at')[:20]
    return JsonResponse({'events': [
        {
            'id': str(ev.id),
            'method': ev.method,
            'source_ip': ev.source_ip or '',
            'body_size': ev.body_size,
            'body_size_display': ev.body_size_display,
            'created_at': ev.created_at.isoformat(),
            'preview_headers': ev.preview_headers,
            'detail_url': reverse('webhooks:event_detail',
                                  kwargs={'id': str(id), 'event_id': str(ev.id)}),
        }
        for ev in events
    ]})


@login_required
def endpoint_test(request, id):
    endpoint = get_object_or_404(WebhookEndpoint, id=id)
    receiver_url = request.build_absolute_uri(
        reverse('webhooks:receive_webhook', kwargs={'slug': endpoint.slug})
    )
    return render(request, 'webhooks/endpoint_test.html', {
        'endpoint': endpoint,
        'receiver_url': receiver_url,
    })


@csrf_exempt
def receive_webhook(request, slug):
    endpoint = WebhookEndpoint.objects.filter(slug=slug, is_active=True).first()
    if not endpoint:
        return HttpResponse('OK', status=200)

    source_ip = (
        request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        .split(',')[0].strip()
    ) or None

    headers = {}
    for key, value in request.META.items():
        if key.startswith('HTTP_'):
            headers[key[5:].replace('_', '-').title()] = value
        elif key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            headers[key.replace('_', '-').title()] = value

    MAX_BODY = 1 * 1024 * 1024
    raw = request.body
    body = raw[:MAX_BODY].decode('utf-8', errors='replace')
    if len(raw) > MAX_BODY:
        body += '\n[body truncated at 1 MB]'
        logger.warning('Webhook body truncated for endpoint %s', endpoint.slug)

    event = WebhookEvent.objects.create(
        endpoint=endpoint,
        method=request.method,
        headers=headers,
        body=body,
        query_params=dict(request.GET.lists()),
        source_ip=source_ip,
    )

    try:
        payload = json.loads(body)
        raw_name = payload.get('event_name', '')
        raw_start = payload.get('event_start', '')
        if ':' in raw_name and raw_start:
            city = raw_name.split(':', 1)[1].strip()
            event_date = datetime.fromisoformat(raw_start.replace('Z', '+00:00')).date()
            from .sheets import get_event_tag
            tag = get_event_tag(city, event_date)
            if tag:
                event.sheet_tag = tag
                event.save(update_fields=['sheet_tag'])
    except Exception:
        pass

    return HttpResponse('OK', status=200)
