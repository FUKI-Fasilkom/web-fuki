from django.apps import AppConfig


class SiwakConfig(AppConfig):
    name = 'siwak'

    def ready(self):
        from . import signals, sso  # noqa: F401
