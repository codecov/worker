from collections import defaultdict
from itertools import repeat
from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import Report

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)


class CSharpProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "CoverageSession"

    @sentry_sdk.trace
    def process(
        self, name: str, content: Element, report_builder: ReportBuilder
    ) -> Report:
        report_builder_session = report_builder.create_report_builder_session(name)
        return from_xml(content, report_builder_session)


def _build_branches(branch_gen):
    branches = defaultdict(list)
    for branch in branch_gen:
        if branch.attrib["vc"] == "0":
            attribs = dict(branch.attrib)
            if "sl" in attribs:
                if attribs.get("offsetend") is not None:
                    branches[int(attribs["sl"])].append(
                        ("%(offset)s:%(offsetend)s" % attribs)
                    )
                else:
                    branches[int(attribs["sl"])].append(("%(offset)s" % attribs))
    return branches


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> Report:
    """
    https://github.com/OpenCover/opencover/issues/293#issuecomment-94598145
    @sl - start line
    @sc - start column
    @el - end line
    @ec - end column
    @bec - branch count
    @bev - branches executed
    @vc - statement executed
    <SequencePoint vc="2" uspid="3" ordinal="0" offset="0" sl="35" sc="8" el="35" ec="9" bec="0" bev="0" fileid="1" />
    """
    ignored_lines = report_builder_session.ignored_lines

    # dict of {"fileid": "path"}
    file_by_id = {}
    file_by_name = {None: None}
    for f in xml.iter("File"):
        filename = report_builder_session.path_fixer(
            f.attrib["fullPath"].replace("\\", "/")
        )
        if filename:
            file_by_id[f.attrib["uid"]] = filename
            file_by_name.setdefault(
                filename,
                report_builder_session.file_class(
                    filename, ignore=ignored_lines.get(filename)
                ),
            )

    for method in xml.iter("Method"):
        fileref = method.find("FileRef")
        if fileref is not None:
            _file = file_by_name[file_by_id.get(fileref.attrib["uid"])]
            if _file is not None:
                branches = _build_branches(method.iter("BranchPoint"))
                branches_get = branches.get
                file_append = _file.append

                for _type, node in zip(repeat(None), method.iter("SequencePoint")):
                    attrib = node.attrib.get
                    sl, el = attrib("sl"), attrib("el")
                    if sl and el:
                        complexity = (
                            int(attrib("cyclomaticComplexity", 0))
                            if _type == CoverageType.method
                            else None
                        )
                        sl, el = int(sl), int(el)
                        vc, bec = int(attrib("vc")), attrib("bec")
                        if bec is not None:
                            bev = attrib("bev")
                            if bec != "0":
                                coverage = "%s/%s" % (bev, bec)
                                _type = _type or CoverageType.branch
                            elif vc > 0:
                                coverage = vc
                            else:
                                coverage = 0
                        else:
                            coverage = vc

                        coverage_type = _type or CoverageType.line
                        # spans > 1 line
                        if el > sl:
                            for ln in range(sl, el + 1):
                                file_append(
                                    ln,
                                    report_builder_session.create_coverage_line(
                                        filename=_file.name,
                                        coverage=coverage,
                                        coverage_type=coverage_type,
                                        missing_branches=branches_get(ln),
                                        complexity=complexity,
                                    ),
                                )
                        # spans = 1 line
                        else:
                            file_append(
                                sl,
                                report_builder_session.create_coverage_line(
                                    filename=_file.name,
                                    coverage=coverage,
                                    coverage_type=coverage_type,
                                    missing_branches=branches_get(sl),
                                    complexity=complexity,
                                ),
                            )

    for v in file_by_name.values():
        report_builder_session.append(v)

    return report_builder_session.output_report()
