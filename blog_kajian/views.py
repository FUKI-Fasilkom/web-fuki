from django.shortcuts import render

# Create your views here.

def blog_kajian_page(request):
    return render(request, 'blog_kajian.html')