from django.urls import path
from . import views

app_name = 'webhooks'

urlpatterns = [
    path('', views.endpoint_list, name='endpoint_list'),
    path('create/', views.endpoint_create, name='endpoint_create'),
    path('tags/', views.tag_list, name='tag_list'),
    path('tags/create/', views.tag_create, name='tag_create'),
    path('tags/<uuid:id>/edit/', views.tag_edit, name='tag_edit'),
    path('tags/<uuid:id>/delete/', views.tag_delete, name='tag_delete'),
    path('<uuid:id>/', views.endpoint_detail, name='endpoint_detail'),
    path('<uuid:id>/delete/', views.endpoint_delete, name='endpoint_delete'),
    path('<uuid:id>/events/<uuid:event_id>/', views.event_detail, name='event_detail'),
    path('<uuid:id>/events/<uuid:event_id>/replay/', views.event_replay, name='event_replay'),
    path('<uuid:id>/events/poll/', views.events_poll, name='events_poll'),
    path('<uuid:id>/events/older/', views.events_load_older, name='events_load_older'),
    path('<uuid:id>/test/', views.endpoint_test, name='endpoint_test'),
    path('receive/<slug:slug>/', views.receive_webhook, name='receive_webhook'),
]
