import dataclasses
from json import loads


class BaseTestCase(object):
    def convert_report_to_better_readable(self, report):
        totals_dict, report_dict = report.to_database()
        report_dict = loads(report_dict)
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
