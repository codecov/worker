from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

_template_service = None


def get_template_service():
    return _get_cached_template_service()


def _get_cached_template_service():
    global _template_service
    if _template_service is None:
        _template_service = TemplateService()
    return _template_service


class TemplateService:
    def __init__(self):
        # this loads the templates from the templates directory in this repository since it's looking for a dir named `templates` next to app.py
        self.env = Environment(
            loader=PackageLoader("app"),
            autoescape=select_autoescape(),
            undefined=StrictUndefined,
        )

    def get_template(self, name, **kwargs):
        template = self.env.get_template(f"{name}")
        return template.render(**kwargs)
