import re
from collections import defaultdict
from io import BytesIO

import sentry_sdk

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import CoverageType, ReportBuilderSession
from services.yaml import read_yaml_field


class GcovProcessor(BaseLanguageProcessor):
    def matches_content(self, content: bytes, first_line: str, name: str) -> bool:
        return b"0:Source:" in content.split(b"\n", 1)[0]

    @sentry_sdk.trace
    def process(
        self,
        content: bytes,
        report_builder_session: ReportBuilderSession,
    ) -> None:
        return from_txt(content, report_builder_session)


ignored_lines = re.compile(r"(\{|\})(\s*\/\/.*)?").match
detect_loop = re.compile(r"^\s+(for|while)\s?\(").match
detect_conditional = re.compile(r"^\s+((if\s?\()|(\} else if\s?\())").match


def from_txt(string: bytes, report_builder_session: ReportBuilderSession) -> None:
    filepath = report_builder_session.filepath
    path_fixer = report_builder_session.path_fixer

    line_iterator = iter(BytesIO(string))
    # clean and strip lines
    filename = next(line_iterator).decode(errors="replace").rstrip("\n")
    filename = filename.split(":")[3].lstrip("./")
    if filepath and filepath.endswith(filename + ".gcov"):
        filename = path_fixer(filepath[:-5]) or path_fixer(filename)
    else:
        filename = path_fixer(filename)
    if not filename:
        return None

    settings = report_builder_session.yaml_field(("parsers", "gcov"))
    detect_branches_in_methods = read_yaml_field(
        settings, ("branch_detection", "method"), False
    )
    detect_branches_in_loops = read_yaml_field(
        settings, ("branch_detection", "loop"), False
    )
    detect_branches_in_conditions = read_yaml_field(
        settings, ("branch_detection", "conditional"), False
    )
    detect_branches_in_macros = read_yaml_field(
        settings, ("branch_detection", "macro"), False
    )

    ignore = False
    ln = None
    next_is_func = False
    data = None

    _cur_branch_detected = None
    _cur_line_branch = None
    line_branches = {}
    lines = defaultdict(list)
    line_types = {}

    for encoded_line in line_iterator:
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
                if (
                    line_types[ln] == CoverageType.method
                    and not detect_branches_in_methods
                ):
                    continue
                # loop
                elif detect_loop(data):
                    line_types[ln] = CoverageType.branch
                    if not detect_branches_in_loops:
                        continue
                # conditional
                elif detect_conditional(data):
                    line_types[ln] = CoverageType.branch
                    if not detect_branches_in_conditions:
                        continue
                # else macro
                elif not detect_branches_in_macros:
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
                line_types[ln] = CoverageType.method
            else:
                line_types[ln] = CoverageType.line
            lines[ln].append(coverage)

            next_is_func = False

    _file = report_builder_session.create_coverage_file(filename, do_fix_path=False)
    for ln, coverages in lines.items():
        _type = line_types[ln]
        branches = line_branches.get(ln)
        if branches:
            coverage = "%s/%s" % tuple(branches)
            _file.append(
                ln,
                report_builder_session.create_coverage_line(coverage, _type),
            )
        else:
            for coverage in coverages:
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(coverage, _type),
                )

    report_builder_session.append(_file)
