import re
import json
from django.shortcuts import render
from django.utils.timezone import datetime
from django.http import HttpResponse
from .forms import HikeForm
from .services.routing import compute_hike_path


def hello_there(request, name):
    return render(
        request,
        'hello/hello_there.html',
        {
            'name': name,
            'date': datetime.now()
        }
    )

def index(request):
    path = None

    if request.method == 'POST':
        start = request.POST.get('start')
        end = request.POST.get('end')
        if start and end:
            try:
                start_coords = tuple(map(float, start.split(',')))
                end_coords = tuple(map(float, end.split(',')))
                path = compute_hike_path(start_coords, end_coords)
            except:
                path = None
    context = {
        'path': json.dumps(path) if path else None,
    }
    return render(request, 'hello/index.html', context)

