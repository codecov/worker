from collections import defaultdict
from itertools import repeat
from xml.etree.ElementTree import Element

import sentry_sdk
from shared.reports.resources import ReportFile

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession


class CSharpProcessor(BaseLanguageProcessor):
    def matches_content(self, content: Element, first_line: str, name: str) -> bool:
        return content.tag == "CoverageSession"

    @sentry_sdk.trace
    def process(
        self, content: Element, report_builder_session: ReportBuilderSession
    ) -> None:
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


def from_xml(xml: Element, report_builder_session: ReportBuilderSession) -> None:
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

    file_by_id: dict[str, ReportFile] = {}
    for f in xml.iter("File"):
        filename = f.attrib["fullPath"].replace("\\", "/")
        _file = report_builder_session.create_coverage_file(filename)
        if _file is not None:
            file_by_id[f.attrib["uid"]] = _file

    for method in xml.iter("Method"):
        fileref = method.find("FileRef")
        if fileref is None:
            continue
        _file = file_by_id.get(fileref.attrib["uid"])
        if not _file:
            continue

        branches = _build_branches(method.iter("BranchPoint"))

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
                        _file.append(
                            ln,
                            report_builder_session.create_coverage_line(
                                coverage,
                                coverage_type,
                                missing_branches=branches.get(ln),
                                complexity=complexity,
                            ),
                        )
                # spans = 1 line
                else:
                    _file.append(
                        sl,
                        report_builder_session.create_coverage_line(
                            coverage,
                            coverage_type,
                            missing_branches=branches.get(sl),
                            complexity=complexity,
                        ),
                    )

    for v in file_by_id.values():
        report_builder_session.append(v)
