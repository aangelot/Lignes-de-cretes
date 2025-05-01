import re
from django.shortcuts import render
from django.utils.timezone import datetime
from django.http import HttpResponse
from .forms import HikeForm
from .services.routing import compute_hike_path

# Replace the existing home function with the one below
def home(request):
    return render(request, "hello/home.html")

def contact(request):
    return render(request, "hello/contact.html")


def hello_there(request, name):
    return render(
        request,
        'hello/hello_there.html',
        {
            'name': name,
            'date': datetime.now()
        }
    )

def plan_hike(request):
    path = None
    if request.method == 'POST':
        form = HikeForm(request.POST)
        if form.is_valid():
            start_lat = float(request.POST.get("start_lat"))
            start_lon = float(request.POST.get("start_lon"))
            end_lat = float(request.POST.get("end_lat"))
            end_lon = float(request.POST.get("end_lon"))

            fmap = compute_hike_path((start_lat, start_lon), (end_lat, end_lon))
            map_html = fmap._repr_html_()
            return render(request, 'hello/plan_hike.html', {'form': form, "map_html": map_html})
    else:
        form = HikeForm()
        return render(request, 'hello/plan_hike.html', {'form': form})

