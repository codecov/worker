from io import BytesIO

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor


class DLSTProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content[-7:] == b"covered")

    def process(
        self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        return from_string(name, content, path_fixer, ignored_lines, sessionid)


def from_string(filename, string, fix, ignored_lines, sessionid):
    if filename:
        # src/file.lst => src/file.d
        filename = fix("%sd" % filename[:-3])

    if not filename:
        # file.d => src/file.d
        last_line = string[string.rfind(b"\n") :].decode(errors="replace").strip()
        filename = last_line.split(" is ", 1)[0]
        if filename.startswith("source "):
            filename = filename[7:]

        filename = fix(filename)
        if not filename:
            return None

    _file = ReportFile(filename, ignore=ignored_lines.get(filename))
    for ln, encoded_line in enumerate(BytesIO(string), start=1):
        line = encoded_line.decode(errors="replace").rstrip("\n")
        try:
            coverage = int(line.split("|", 1)[0].strip())
            _file[ln] = ReportLine.create(coverage, None, [[sessionid, coverage]])
        except Exception:
            # not a vaild line
            pass

    report = Report()
    report.append(_file)
    return report
