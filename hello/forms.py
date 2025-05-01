from django import forms

class HikeForm(forms.Form):
    start_lat = forms.FloatField(label="Start Latitude")
    start_lon = forms.FloatField(label="Start Longitude")
    end_lat = forms.FloatField(label="End Latitude")
    end_lon = forms.FloatField(label="End Longitude")