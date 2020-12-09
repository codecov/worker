from collections import defaultdict
from itertools import chain, repeat

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class CSharpProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "CoverageSession")

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml):
        return from_xml(content, path_fixer, ignored_lines, sessionid)


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


def from_xml(xml, fix, ignored_lines, sessionid):
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
    # dict of {"fileid": "path"}
    file_by_id = {}
    file_by_id_get = file_by_id.get
    file_by_name = {None: None}
    for f in xml.iter("File"):
        filename = fix(f.attrib["fullPath"].replace("\\", "/"))
        if filename:
            file_by_id[f.attrib["uid"]] = filename
            file_by_name.setdefault(
                filename, ReportFile(filename, ignore=ignored_lines.get(filename))
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
                            if _type == "m"
                            else None
                        )
                        sl, el = int(sl), int(el)
                        vc, bec = int(attrib("vc")), attrib("bec")
                        if bec is not None:
                            bev = attrib("bev")
                            if bec != "0":
                                coverage = "%s/%s" % (bev, bec)
                                _type = _type or "b"
                            elif vc > 0:
                                coverage = vc
                            else:
                                coverage = 0
                        else:
                            coverage = vc

                        # spans > 1 line
                        if el > sl:
                            for ln in range(sl, el + 1):
                                file_append(
                                    ln,
                                    ReportLine.create(
                                        coverage=coverage,
                                        type=_type,
                                        sessions=[
                                            [
                                                sessionid,
                                                coverage,
                                                branches_get(ln),
                                                None,
                                                complexity,
                                            ]
                                        ],
                                        complexity=complexity,
                                    ),
                                )

                        # spans = 1 line
                        else:
                            file_append(
                                sl,
                                ReportLine.create(
                                    coverage=coverage,
                                    type=_type,
                                    sessions=[
                                        [
                                            sessionid,
                                            coverage,
                                            branches_get(sl),
                                            None,
                                            complexity,
                                        ]
                                    ],
                                    complexity=complexity,
                                ),
                            )

    report = Report()
    for v in file_by_name.values():
        report.append(v)

    return report
