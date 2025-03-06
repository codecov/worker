import logging
from collections import defaultdict

import sentry_sdk
from lxml.etree import Element
from shared.utils.merge import LineType, branch_type
from timestring import Date

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession

log = logging.getLogger(__name__)


class JacocoProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "report"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
    """
    nr = line number
    mi = missed instructions
    ci = covered instructions
    mb = missed branches
    cb = covered branches
    """
    path_fixer = report_builder_session.path_fixer
    if max_age := report_builder_session.yaml_field(
        ("codecov", "max_report_age"), "12h ago"
    ):
        try:
            timestamp = next(xml.iter("sessioninfo")).get("start")
            if timestamp and Date(timestamp) < max_age:
                # report expired over 12 hours ago
                raise ReportExpiredException("Jacoco report expired %s" % timestamp)

        except StopIteration:
            pass

    project = xml.attrib.get("name", "")
    project = "" if " " in project else project.strip("/")

    partials_as_hits = report_builder_session.yaml_field(
        ("parsers", "jacoco", "partials_as_hits"), False
    )

    def try_to_fix_path(path: str) -> str | None:
        if project:
            # project/package/path
            filename = path_fixer("%s/%s" % (project, path))
            if filename:
                return filename

            # project/src/main/java/package/path
            filename = path_fixer("%s/src/main/java/%s" % (project, path))
            if filename:
                return filename

        # package/path
        return path_fixer(path)

    for package in xml.iter("package"):
        base_name = package.attrib["name"]

        file_method_complixity: dict[str, dict[int, tuple[int, int]]] = defaultdict(
            dict
        )
        # Classes complexity
        for _class in package.iter("class"):
            class_name = _class.attrib["name"]
            if "$" not in class_name:
                method_complixity = file_method_complixity[class_name]
                # Method Complexity
                for method in _class.iter("method"):
                    ln = int(method.attrib.get("line", 0))
                    if ln > 0:
                        for counter in method.iter("counter"):
                            if counter.attrib["type"] == "COMPLEXITY":
                                m = int(counter.attrib["missed"])
                                c = int(counter.attrib["covered"])
                                method_complixity[ln] = (c, m + c)
                                break

        # Statements
        for source in package.iter("sourcefile"):
            source_name = "%s/%s" % (base_name, source.attrib["name"])
            filename = try_to_fix_path(source_name)
            if filename is None:
                continue

            method_complixity = file_method_complixity[source_name.split(".")[0]]

            _file = report_builder_session.create_coverage_file(
                filename, do_fix_path=False
            )
            assert _file is not None, (
                "`create_coverage_file` with pre-fixed path is infallible"
            )

            for line in source.iter("line"):
                attr = line.attrib
                cov: int | str
                if attr["mb"] != "0":
                    cov = "%s/%s" % (attr["cb"], int(attr["mb"]) + int(attr["cb"]))
                    coverage_type = CoverageType.branch

                elif attr["cb"] != "0":
                    cov = "%s/%s" % (attr["cb"], attr["cb"])
                    coverage_type = CoverageType.branch

                else:
                    cov = int(attr["ci"])
                    coverage_type = CoverageType.line

                if (
                    coverage_type == CoverageType.branch
                    and branch_type(cov) == LineType.partial
                    and partials_as_hits
                ):
                    cov = 1

                ln = int(attr["nr"])
                if ln > 0:
                    complexity = method_complixity.get(ln)
                    if complexity:
                        coverage_type = CoverageType.method
                    # add line to file
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            cov,
                            coverage_type,
                            complexity=complexity,
                        ),
                    )
                else:
                    log.warning(
                        f"Jacoco report has an invalid coverage line: nr={ln}. Skipping processing line."
                    )

            # append file to report
            report_builder_session.append(_file)
