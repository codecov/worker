import typing

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from helpers.exceptions import CorruptRawReportError
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder
from services.yaml import read_yaml_field


class VOneProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return "coverage" in content or "RSpec" in content or "MiniTest" in content

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        if "RSpec" in content:
            content = content["RSpec"]

        elif "MiniTest" in content:
            content = content["MiniTest"]

        return from_json(
            content,
            path_fixer,
            ignored_lines,
            sessionid,
            read_yaml_field(repo_yaml, ("parsers", "v1")) or {},
        )


def _list_to_dict(lines):
    """
    in:  [None, 1] || {"1": 1}
    out: {"1": 1}
    """
    if type(lines) is list:
        if len(lines) > 1:
            return dict(
                [
                    (ln, cov)
                    for ln, cov in enumerate(lines[1:], start=1)
                    if cov is not None
                ]
            )
        else:
            return {}
    elif "lines" in lines:
        # lines format here is
        # { "lines": [ None, None, 1, 1,...] },
        # We add a fake first line because this function starts from line at index 1 not 0
        return _list_to_dict([None] + lines["lines"])
    else:
        return lines or {}


def from_json(json, fix, ignored_lines, sessionid, config):
    if type(json["coverage"]) is dict:
        # messages = json.get('messages', {})
        report = Report()
        for fn, lns in json["coverage"].items():
            fn = fix(fn)
            if fn is None:
                continue

            lns = _list_to_dict(lns)
            print(lns)
            if lns:
                _file = ReportFile(fn, ignore=ignored_lines.get(fn))
                for ln, cov in lns.items():
                    try:
                        line_number = int(ln)
                    except ValueError:
                        raise CorruptRawReportError(
                            "v1",
                            "file dictionaries expected to have integers, not strings",
                        )
                    if line_number > 0:
                        if isinstance(cov, str):
                            try:
                                int(cov)
                            except Exception:
                                pass
                            else:
                                cov = int(cov)

                        # message = messages.get(fn, {}).get(ln)
                        _file[line_number] = ReportLine.create(
                            coverage=cov,
                            type="b" if type(cov) in (str, bool) else None,
                            sessions=[[sessionid, cov]],
                        )

                report.append(_file)
        return report
