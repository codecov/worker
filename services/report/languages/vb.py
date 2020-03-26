from covreports.reports.resources import Report, ReportFile
from covreports.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor


class VbProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "results")

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml):
        return from_xml(content, path_fixer, ignored_lines, sessionid)


def from_xml(xml, fix, ignored_lines, sessionid):
    report = Report()
    for module in xml.iter("module"):
        file_by_source = {}
        # loop through sources
        for sf in module.iter("source_file"):
            filename = fix(sf.attrib["path"].replace("\\", "/"))
            if filename:
                file_by_source[sf.attrib["id"]] = ReportFile(
                    filename, ignore=ignored_lines.get(filename)
                )

        if file_by_source:
            # loop through each line
            for line in module.iter("range"):
                line = line.attrib
                _file = file_by_source.get(line["source_id"])
                if _file is not None:
                    coverage = line["covered"]
                    coverage = (
                        1 if coverage == "yes" else 0 if coverage == "no" else True
                    )
                    for ln in range(int(line["start_line"]), int(line["end_line"]) + 1):
                        _file[ln] = ReportLine(coverage, None, [[sessionid, coverage]])

            # add files
            for v in file_by_source.values():
                report.append(v)

    return report
