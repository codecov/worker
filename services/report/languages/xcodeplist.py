import plistlib

import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession


class XCodePlistProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        if name:
            return name.endswith("xccoverage.plist")
        if content.find(b'<plist version="1.0">') > -1 and content.startswith(b"<?xml"):
            return True
        return False

    @sentry_sdk.trace
    def process(
        self, content: bytes, report_builder_session: ReportBuilderSession
    ) -> None:
        return from_xml(content, report_builder_session)


def from_xml(xml: bytes, report_builder_session: ReportBuilderSession) -> None:
    objects = plistlib.loads(xml)["$objects"]

    for obj in objects[2]["NS.objects"]:
        for sourceFile in objects[objects[obj["CF$UID"]]["sourceFiles"]["CF$UID"]][
            "NS.objects"
        ]:
            # get filename
            filename = objects[
                objects[sourceFile["CF$UID"]]["documentLocation"]["CF$UID"]
            ]
            _file = report_builder_session.create_coverage_file(filename)
            if _file is None:
                continue

            # loop lines
            for ln, line in enumerate(
                objects[objects[sourceFile["CF$UID"]]["lines"]["CF$UID"]]["NS.objects"],
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
                        report_builder_session.create_coverage_line(
                            coverage,
                            CoverageType.branch if partials else CoverageType.line,
                            partials=partials,
                        ),
                    )

            # append file to report
            report_builder_session.append(_file)
