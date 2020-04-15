from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class VbTwoProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "CoverageDSPriv")

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml):
        return from_xml(content, path_fixer, ignored_lines, sessionid)


def from_xml(xml, fix, ignored_lines, sessionid):
    file_by_source = {}
    for source in xml.iter("SourceFileNames"):
        filename = fix(source.find("SourceFileName").text.replace("\\", "/"))
        if filename:
            file_by_source[source.find("SourceFileID").text] = ReportFile(
                filename, ignore=ignored_lines.get(filename)
            )

    for line in xml.iter("Lines"):
        _file = file_by_source.get(line.find("SourceFileID").text)
        if _file is not None:
            # 0 == hit, 1 == partial, 2 == miss
            cov = line.find("Coverage").text
            cov = 1 if cov == "0" else 0 if cov == "2" else True
            for ln in range(
                int(line.find("LnStart").text), int(line.find("LnEnd").text) + 1
            ):
                _file[ln] = ReportLine(cov, None, [[sessionid, cov]])

    report = Report()
    for value in file_by_source.values():
        report.append(value)
    return report
