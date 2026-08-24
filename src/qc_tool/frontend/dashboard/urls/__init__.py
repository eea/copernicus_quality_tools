"""Dashboard URL composition.

Every named route is registered through ``protected_path`` so its public/private
visibility, authentication, authorization, and HTTP methods come from one policy
registry.
"""

from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from qc_tool.frontend.dashboard.urls.api import urlpatterns as api_patterns
from qc_tool.frontend.dashboard.urls.data import urlpatterns as data_patterns
from qc_tool.frontend.dashboard.urls.pages import urlpatterns as page_patterns
from qc_tool.frontend.dashboard.urls.workers import urlpatterns as worker_patterns


urlpatterns = [
    *page_patterns,
    *data_patterns,
    *api_patterns,
    *worker_patterns,
    *staticfiles_urlpatterns(),
]
