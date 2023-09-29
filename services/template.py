from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape


class TemplateService:
    env = None

    def __init__(self):
        if TemplateService.env is None:
            # this loads the templates from the templates directory in this repository since it's looking for a dir named `templates` next to app.py
            TemplateService.env = Environment(
                loader=PackageLoader("app"),
                autoescape=select_autoescape(),
                undefined=StrictUndefined,
            )

    def get_template(self, name):
        template = TemplateService.env.get_template(f"{name}")
        return template
