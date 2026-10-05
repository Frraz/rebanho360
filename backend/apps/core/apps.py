from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Núcleo compartilhado"

    def ready(self):
        from apps.core import signals

        signals.conectar()
