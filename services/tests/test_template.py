import pytest
from jinja2.exceptions import TemplateNotFound, UndefinedError

from services.template import TemplateService


class TestTemplate(object):
    def test_get_template(self):
        ts = TemplateService()
        template = ts.get_template("test.txt")
        populated_template = template.render(**dict(username="test_username"))
        assert populated_template == "Test template test_username"

    def test_get_template_html(self):
        ts = TemplateService()
        template = ts.get_template("test.html")
        populated_template = template.render(**dict(username="test_username"))
        expected_result = """<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document</title>
</head>

<body>
    <p>
        test template test_username
    </p>
</body>

</html>"""
        for expected_line, actual_line in zip(
            expected_result.splitlines(), populated_template.splitlines()
        ):
            assert expected_line == actual_line

    def test_get_template_no_kwargs(self):
        ts = TemplateService()
        template = ts.get_template("test.txt")
        with pytest.raises(UndefinedError):
            template.render(not_username="")

    def test_get_template_non_existing(self):
        ts = TemplateService()
        with pytest.raises(TemplateNotFound):
            ts.get_template("nonexistent")
