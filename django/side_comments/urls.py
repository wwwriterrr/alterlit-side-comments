from django.urls import path

from api.side_comments import views

# в api/urls.py: path('side_comments_v2/', include('api.side_comments.urls')),
urlpatterns = [
    path('', views.SideCommentsView.as_view(), name='side_comments'),
]
