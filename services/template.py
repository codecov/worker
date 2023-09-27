from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape


def get_template_service():
    return TemplateService()


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
