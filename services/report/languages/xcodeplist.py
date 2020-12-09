import plistlib

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine, LineSession
from services.report.languages.base import BaseLanguageProcessor


class XCodePlistProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line, name):
        if name:
            return name.endswith("xccoverage.plist")
        if content.find(b'<plist version="1.0">') > -1 and content.startswith(b"<?xml"):
            return True

    def process(
        self, name, content: bytes, path_fixer, ignored_lines, sessionid, repo_yaml=None
    ):
        return from_xml(content, path_fixer, ignored_lines, sessionid)


def from_xml(xml: bytes, fix, ignored_lines, sessionid):
    objects = plistlib.loads(xml)["$objects"]

    _report = Report()

    for obj in objects[2]["NS.objects"]:
        for sourceFile in objects[objects[obj["CF$UID"]]["sourceFiles"]["CF$UID"]][
            "NS.objects"
        ]:
            # get filename
            filename = fix(
                objects[objects[sourceFile["CF$UID"]]["documentLocation"]["CF$UID"]]
            )
            if filename:
                # create a file
                _file = ReportFile(filename, ignore=ignored_lines.get(filename))
                # loop lines
                for ln, line in enumerate(
                    objects[objects[sourceFile["CF$UID"]]["lines"]["CF$UID"]][
                        "NS.objects"
                    ],
                    start=1,
                ):
                    # get line object
                    line = objects[line["CF$UID"]]
                    # is line is tracked in coverage?
                    if line["x"] is not False:
                        # does line have partial content?
                        if line["s"]["CF$UID"] != 0:
                            partials = []
                            hits = 0
                            # loop branches
                            for branch in objects[line["s"]["CF$UID"]]["NS.objects"]:
                                # get branch object
                                branch = objects[branch["CF$UID"]]
                                # skip ending branches
                                if branch["len"] != 2:  # ending method
                                    # append partials
                                    partials.append(
                                        [
                                            branch["c"],
                                            branch["c"] + branch["len"],
                                            branch["x"],
                                        ]
                                    )
                                    hits += 1 if branch["x"] > 0 else 0
                            # set coverage ratio
                            coverage = "%s/%s" % (hits, len(partials))

                        else:
                            # statement line
                            partials = None
                            coverage = line["c"]

                        # append line to report
                        _file.append(
                            ln,
                            ReportLine.create(
                                coverage=coverage,
                                type="b" if partials else None,
                                sessions=[
                                    LineSession(
                                        id=sessionid,
                                        coverage=coverage,
                                        partials=partials,
                                    )
                                ],
                            ),
                        )
                # append file to report
                _report.append(_file)

    return _report
