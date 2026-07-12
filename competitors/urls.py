from django.urls import path

from . import views

app_name = 'competitors'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('sources/create/', views.source_create, name='source_create'),
    path('sources/<uuid:id>/delete/', views.source_delete, name='source_delete'),
    path('sources/<uuid:id>/refresh/', views.source_refresh, name='source_refresh'),
    path('refresh-all/', views.refresh_all, name='refresh_all'),
]
