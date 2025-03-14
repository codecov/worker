import dataclasses
from json import loads

from services.report import legacy_totals


class BaseTestCase(object):
    def convert_report_to_better_readable(self, report):
        report_json, _chunks, _totals = report.serialize()

        totals_dict = legacy_totals(report)
        report_dict = loads(report_json)
        report_dict.pop("totals")
        archive_dict = {}
        for filename in report.files:
            file_report = report.get(filename)
            lines = []
            for line_number, line in file_report.lines:
                (
                    coverage,
                    line_type,
                    sessions,
                    messages,
                    complexity,
                    datapoints,
                ) = dataclasses.astuple(line)
                sessions = [list(s) for s in sessions]
                lines.append(
                    (
                        line_number,
                        coverage,
                        line_type,
                        sessions,
                        messages,
                        complexity,
                        datapoints,
                    )
                    if datapoints is not None
                    else (
                        line_number,
                        coverage,
                        line_type,
                        sessions,
                        messages,
                        complexity,
                    )
                )
            archive_dict[filename] = lines
        return {"archive": archive_dict, "report": report_dict, "totals": totals_dict}
