"""Dashboard URL composition.

Every named route is registered through ``protected_path`` so its public/private
visibility, authentication, authorization, and HTTP methods come from one policy
registry.
"""

from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from qc_tool.frontend.dashboard.urls.api_access import urlpatterns as api_patterns
from qc_tool.frontend.dashboard.urls.boundaries import (
    urlpatterns as boundary_patterns,
)
from qc_tool.frontend.dashboard.urls.compatibility import (
    urlpatterns as compatibility_patterns,
)
from qc_tool.frontend.dashboard.urls.configuration import (
    urlpatterns as configuration_patterns,
)
from qc_tool.frontend.dashboard.urls.deliveries import (
    urlpatterns as delivery_patterns,
)
from qc_tool.frontend.dashboard.urls.jobs import urlpatterns as job_patterns
from qc_tool.frontend.dashboard.urls.overview import (
    urlpatterns as overview_patterns,
)
from qc_tool.frontend.dashboard.urls.products import (
    urlpatterns as product_patterns,
)
from qc_tool.frontend.dashboard.urls.uploads import urlpatterns as upload_patterns
from qc_tool.frontend.dashboard.urls.workers import urlpatterns as worker_patterns


urlpatterns = [
    *overview_patterns,
    *delivery_patterns,
    *product_patterns,
    *job_patterns,
    *upload_patterns,
    *boundary_patterns,
    *configuration_patterns,
    *api_patterns,
    *worker_patterns,
    *compatibility_patterns,
    *staticfiles_urlpatterns(),
]
