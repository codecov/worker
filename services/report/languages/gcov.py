import re
import typing
from collections import defaultdict
from io import BytesIO

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder
from services.yaml import read_yaml_field


class GcovProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return detect(content)

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        settings = read_yaml_field(repo_yaml, ("parsers", "gcov"))
        return from_txt(name, content, path_fixer, ignored_lines, sessionid, settings)


ignored_lines = re.compile(r"(\{|\})(\s*\/\/.*)?").match
detect_loop = re.compile(r"^\s+(for|while)\s?\(").match
detect_conditional = re.compile(r"^\s+((if\s?\()|(\} else if\s?\())").match


def detect(report):
    return b"0:Source:" in report.split(b"\n", 1)[0]


def from_txt(name, string, fix, ignored_lines, sesisonid, settings):
    line_iterator = iter(BytesIO(string))
    # clean and strip lines
    filename = next(line_iterator).decode(errors="replace").rstrip("\n")
    filename = filename.split(":")[3].lstrip("./")
    if name and name.endswith(filename + ".gcov"):
        filename = fix(name[:-5]) or fix(filename)
    else:
        filename = fix(filename)
    if not filename:
        return None

    report = Report()
    report.append(
        _process_gcov_file(
            filename, ignored_lines.get(filename), line_iterator, sesisonid, settings
        )
    )
    return report


def _process_gcov_file(filename, ignore_func, gcov_line_iterator, sesisonid, settings):
    ignore = False
    ln = None
    next_is_func = False
    data = None

    _cur_branch_detected = None
    _cur_line_branch = None
    line_branches = {}
    lines = defaultdict(list)
    line_types = {}

    for encoded_line in gcov_line_iterator:
        line = encoded_line.decode(errors="replace").rstrip("\n")
        if "LCOV_EXCL_START" in line:
            ignore = True

        elif "LCOV_EXCL_END" in line or "LCOV_EXCL_STOP" in line:
            ignore = False

        elif ignore:
            pass

        elif "LCOV_EXCL_LINE" in line:
            pass

        elif line[:4] == "func":
            # for next line
            next_is_func = True

        elif line[:4] == "bran" and ln in lines:
            if _cur_branch_detected is False:
                # skip read_yaml_fielding/regexp checks because of repeated branchs
                continue

            elif _cur_branch_detected is None:
                _cur_branch_detected = False  # first set to false, prove me true

                # class
                if line_types[ln] == "m":
                    if (
                        read_yaml_field(settings, ("branch_detection", "method"))
                        is not True
                    ):
                        continue
                # loop
                elif detect_loop(data):
                    line_types[ln] = "b"
                    if (
                        read_yaml_field(settings, ("branch_detection", "loop"))
                        is not True
                    ):
                        continue
                # conditional
                elif detect_conditional(data):
                    line_types[ln] = "b"
                    if (
                        read_yaml_field(settings, ("branch_detection", "conditional"))
                        is not True
                    ):
                        continue
                # else macro
                elif (
                    read_yaml_field(settings, ("branch_detection", "macro")) is not True
                ):
                    continue

                _cur_branch_detected = True  # proven true
                _cur_line_branch = line_branches.setdefault(ln, [0, 0])

            # add a hit
            if "taken 0" not in line and "never executed" not in line:
                _cur_line_branch[0] += 1

            # add to total
            _cur_line_branch[1] += 1

        elif line[:4] == "call":
            continue

        else:
            _cur_branch_detected = None
            _cur_line_branch = None

            line = line.split(":", 2)
            if len(line) != 3:
                ln = None
                continue

            elif line[2].strip() == "}":
                # skip ending bracket lines
                continue

            elif line[2].startswith("@implementation"):
                # skip @implementation string;
                continue

            if filename.endswith(".swift"):
                # swift if reversed
                ln, hit, data = tuple(line)
            else:
                hit, ln, data = tuple(line)

            if ignored_lines(data):
                # skip bracket lines
                ln = None
                continue

            elif "-" in hit:
                ln = None
                continue

            hit = hit.strip()
            try:
                ln = int(ln.strip())
            except Exception:
                continue

            if hit == "#####":
                if data.strip().startswith(("inline", "static")):
                    ln = None
                    continue

                coverage = 0

            elif hit == "=====":
                coverage = 0

            else:
                try:
                    coverage = int(hit)
                except Exception:
                    # https://app.getsentry.com/codecov/v4/issues/125373723/
                    ln = None
                    continue

            if next_is_func:
                line_types[ln] = "m"
            else:
                line_types[ln] = None
            lines[ln].append(coverage)

            next_is_func = False

    _file = ReportFile(filename, ignore=ignore_func)
    for ln, coverages in lines.items():
        _type = line_types[ln]
        branches = line_branches.get(ln)
        if branches:
            coverage = "%s/%s" % tuple(branches)
            _file.append(
                ln, ReportLine.create(coverage, _type, [[sesisonid, coverage]])
            )
        else:
            for coverage in coverages:
                _file.append(
                    ln, ReportLine.create(coverage, _type, [[sesisonid, coverage]])
                )

    return _file
