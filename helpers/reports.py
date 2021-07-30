from collections import namedtuple

null = namedtuple("_", ["totals"])(None)


def get_totals_from_file_in_reports(report, path):
    return report.get(path, null).totals
