import pytest
from jinja2.exceptions import UndefinedError

from services.template import get_template_service


class TestTemplate(object):
    def test_idempotent_service(self):
        first = get_template_service()
        second = get_template_service()
        assert id(first) == id(second)

    def test_get_template(self):
        ts = get_template_service()
        populated_template = ts.get_template(
            "test.txt", **dict(username="test_username")
        )
        assert populated_template == "Test template test_username"

    def test_get_template_html(self):
        ts = get_template_service()
        populated_template = ts.get_template(
            "test.html", **dict(username="test_username")
        )
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
        ts = get_template_service()
        with pytest.raises(UndefinedError):
            ts.get_template("test.txt")
