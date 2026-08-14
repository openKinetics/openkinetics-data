"""ASGI config for OpenKinetics Data."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openkinetics_data.settings")

application = get_asgi_application()

