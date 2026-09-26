from django.http import HttpResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from reports.views import dashboard


def health(request):
    return HttpResponse('ok')


@login_required
def reference_guide(request):
    return render(request, 'reference_guide.html')


@login_required
def home(request):
    return dashboard(request)
