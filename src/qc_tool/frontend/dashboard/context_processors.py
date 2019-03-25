from django.conf import settings # import the settings file

def show_logo(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {'SHOW_LOGO': settings.SHOW_LOGO != "no"}