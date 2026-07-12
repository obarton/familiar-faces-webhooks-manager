from django.urls import path

from . import views

app_name = 'competitors'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('landscape/', views.landscape, name='landscape'),
    path('landscape/generate/', views.landscape_generate, name='landscape_generate'),
    path('sources/create/', views.source_create, name='source_create'),
    path('sources/<uuid:id>/', views.competitor_detail, name='competitor_detail'),
    path('sources/<uuid:id>/summary/', views.competitor_summary, name='competitor_summary'),
    path('sources/<uuid:id>/delete/', views.source_delete, name='source_delete'),
    path('sources/<uuid:id>/refresh/', views.source_refresh, name='source_refresh'),
    path('refresh-all/', views.refresh_all, name='refresh_all'),
]
