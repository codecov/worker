import plistlib

import sentry_sdk
from shared.reports.resources import Report, ReportFile
from shared.reports.types import LineSession, ReportLine

from services.path_fixer import PathFixer
from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder


class XCodePlistProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        if name:
            return name.endswith("xccoverage.plist")
        if content.find(b'<plist version="1.0">') > -1 and content.startswith(b"<?xml"):
            return True

    @sentry_sdk.trace
    def process(
        self, name: str, content: bytes, report_builder: ReportBuilder
    ) -> Report:
        return from_xml(
            content,
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
        )


def from_xml(xml: bytes, fix: PathFixer, ignored_lines: dict, sessionid: int):
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
