import os

from django import template

register = template.Library()


@register.filter
def filename(value):
    """Nama berkas saja (tanpa folder) dari FieldFile / path, untuk placeholder file."""
    name = getattr(value, "name", value) or ""
    return os.path.basename(str(name))
