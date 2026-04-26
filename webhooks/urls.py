from django.urls import path
from . import views

app_name = 'webhooks'

urlpatterns = [
    path('', views.endpoint_list, name='endpoint_list'),
    path('create/', views.endpoint_create, name='endpoint_create'),
    path('<uuid:id>/', views.endpoint_detail, name='endpoint_detail'),
    path('<uuid:id>/delete/', views.endpoint_delete, name='endpoint_delete'),
    path('<uuid:id>/events/<uuid:event_id>/', views.event_detail, name='event_detail'),
    path('<uuid:id>/events/poll/', views.events_poll, name='events_poll'),
    path('receive/<slug:slug>/', views.receive_webhook, name='receive_webhook'),
]
