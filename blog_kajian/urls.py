from django.urls import path
from .views import *

urlpatterns = [
    path('', blog_kajian_page, name='blog_kajian'),
    path('detail/<int:id>/', kajian_detail, name='kajian_detail'),
]