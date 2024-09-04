import typing
from collections import defaultdict
from fractions import Fraction

import sentry_sdk
from shared.reports.resources import Report,ReportFile
from shared.utils.merge import partials_to_line

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import (
    CoverageType,
    ReportBuilder,
    ReportBuilderSession,
)
from services.yaml import read_yaml_field


class NodeProcessor(BaseLanguageProcessor):
    def matches_content(self, content: dict, first_line: str, name: str) -> bool:
        return isinstance(content, dict) and all(
            isinstance(data, dict) for data in content.values()
        )

    @sentry_sdk.trace
    def process(
        self, name: str, content: dict, report_builder: ReportBuilder
    ) -> Report:
        return from_json(content, report_builder.create_report_builder_session(name))


def get_line_coverage(location, cov, line_type):
    if location.get("skip"):
        return None, None, None

    sl, sc, el, ec = get_location(location)

    if not sl or (sc + 1 == ec and sl == el):
        return None, None, None

    if line_type != "m" and sl == el and sc != 0:
        partial = [sc, ec, cov]
    else:
        partial = None

    return sl, cov, partial


def get_location(node):
    try:
        if "loc" in node:
            return (
                node["loc"]["start"]["line"],
                node["loc"]["start"]["column"],
                node["loc"]["end"]["line"],
                node["loc"]["end"]["column"],
            )
        elif "start" in node:
            return (
                node["start"]["line"],
                node["start"]["column"],
                node["end"]["line"],
                node["end"]["column"],
            )
        else:
            return (
                node["locations"][0]["start"]["line"],
                node["locations"][0]["start"]["column"],
                node["locations"][-1]["end"]["line"],
                node["locations"][-1]["end"]["column"],
            )
    except Exception:
        return (None, None, None, None)


def must_be_dict(value):
    if not isinstance(value, dict):
        return {}
    else:
        return value


def next_from_json(report_dict: dict, report_builder_session: ReportBuilderSession) -> Report:
    fix, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )
    for filename, data in report_dict.items():
        name = fix(filename)
        if name is None:
            name = fix(filename.replace("lib/", "src/", 1))
            if name is None:
                continue

        _file = report_builder_session.file_class(name, ignore=ignored_lines.get(name))

        if "lineData" in data:
            jscoverage(_file, data, report_builder_session)
            report_builder_session.append(_file)
            continue

        if data.get("data"):
            # why. idk. node is like that.
            data = data["data"]

        ifs = {}
        _ifends = {}
        for bid, branch in must_be_dict(data.get("branchMap")).items():
            if branch.get("skip") is not True:
                if branch.get("type") == "if":
                    # first skip ifs
                    sl, sc, el, ec = get_location(branch)
                    ifs[sl] = (sc, el, ec)

                else:
                    line_parts = defaultdict(list)
                    line_cov = defaultdict(list)
                    for lid, location in enumerate(branch["locations"]):
                        ln, cov, partials = get_line_coverage(
                            location, data["b"][bid][lid], "b"
                        )
                        if ln:
                            line_parts[ln].append(partials)
                            line_cov[ln].append(cov)
                            if ln == location["end"]["line"]:
                                _ifends[location["end"]["line"]] = location["end"][
                                    "column"
                                ]

                    for ln, partials in line_parts.items():
                        partials = list(filter(None, partials))
                        if len(partials) > 1:
                            branches = [
                                str(i)
                                for i, partial in enumerate(partials)
                                if partial and partial[2] == 0
                            ]
                            cov = "%d/%d" % (
                                len(partials) - len(branches),
                                len(partials),
                            )
                            partials = sorted(partials, key=lambda p: p[0])
                        else:
                            branches = None
                            cov = line_cov[ln][0]
                            partials = None
                        _file.append(
                            ln,
                            report_builder_session.create_coverage_line(
                                filename=name,
                                coverage=cov,
                                coverage_type=CoverageType.branch,
                                partials=partials,
                                missing_branches=branches,
                            ),
                        )

        # statements
        inlines = {}
        line_parts = defaultdict(list)
        line_cov = defaultdict(list)
        for sid, statement in must_be_dict(data.get("statementMap")).items():
            if statement.get("skip") is not True:
                ln, cov, partials = get_line_coverage(statement, data["s"][sid], None)
                if ln:
                    sl, sc, el, ec = get_location(statement)
                    if ifs.get(ln) == (sc, el, ec):
                        # we will chop it of later
                        if partials:
                            inlines[ln] = partials

                    else:
                        line_parts[ln].append(partials)
                        line_cov[ln].append(cov)

        for ln, partials in line_parts.items():
            partials = sorted(filter(None, partials), key=lambda p: p[0])
            cov = line_cov[ln][0]
            line = _file.get(ln)
            if line and line.sessions[0].partials is not None:
                continue
            else:
                _file.append(
                    ln,
                    report_builder_session.create_coverage_line(
                        filename=name,
                        coverage=cov,
                        coverage_type=CoverageType.line,
                        partials=partials,
                    ),
                )

        for bid, branch in must_be_dict(data.get("branchMap")).items():
            # single stmt ifs only
            if branch.get("skip") is not True and branch.get("type") == "if":
                sl, sc, el, ec = get_location(branch)
                if sl:
                    branches = data["b"][bid]
                    tb = len(branches)
                    cov = "%s/%s" % (tb - branches.count(0), tb)
                    mb = [str(i) for i, b in enumerate(branches) if b == 0]

                    line = _file.get(sl)
                    if line:
                        inline_part = inlines.pop(sl, None)
                        if inline_part:
                            cur_partials = line.sessions[-1].partials
                            if not cur_partials:
                                _, cov, partials = get_line_coverage(branch, cov, "b")
                                _file.append(sl, report_builder_session.create_coverage_line(
                                    filename=name,
                                    coverage=cov,
                                    coverage_type=CoverageType.branch,
                                    missing_branches=mb,
                                    partials=partials,
                                ))
                                continue

                            sc, ec = sc + 4, cur_partials[0][0] - 2
                            isc, iec, icov = inline_part
                            if sc > ec:
                                cur_partials.append(
                                    [cur_partials[-1][1] + 2, iec, icov]
                                )
                                _file.append(sl, report_builder_session.create_coverage_line(
                                    filename=name,
                                    coverage=cov,
                                    coverage_type=CoverageType.branch,
                                    missing_branches=mb,
                                    partials=cur_partials,
                                ))
                            else:
                                partials = [[sc, ec, cov]]
                                found = False
                                for p in cur_partials:
                                    if (p[0], p[1]) != (ec + 2, iec):
                                        # add these partials
                                        partials.append(p)
                                    elif p[2] == 0 or isinstance(p[2], str):
                                        # dont add trimmed, this part was missed
                                        partials.append(p)
                                    else:
                                        partials.append([ec + 2, iec, icov])
                                _file.append(sl, report_builder_session.create_coverage_line(
                                    filename=name,
                                    coverage=cov,
                                    coverage_type=CoverageType.branch,
                                    missing_branches=mb,
                                    partials=sorted(partials, key=lambda p: p[0]),
                                ))

                        else:
                            # if ( exp && expr )
                            # change to branch
                            _file.append(sl, report_builder_session.create_coverage_line(
                                filename=name,
                                coverage=cov,
                                coverage_type=CoverageType.branch,
                                missing_branches=mb,
                                partials=_file[sl].sessions[-1].partials,
                            ))

                    else:
                        _file.append(
                            sl,
                            report_builder_session.create_coverage_line(
                                filename=name,
                                coverage=cov,
                                coverage_type=CoverageType.branch,
                                missing_branches=mb,
                            ),
                        )

        for fid, func in must_be_dict(data["fnMap"]).items():
            if func.get("skip") is not True:
                ln, cov, partials = get_line_coverage(func, data["f"][fid], "m")
                if ln:
                    _file.append(
                        ln,
                        report_builder_session.create_coverage_line(
                            filename=name,
                            coverage=cov,
                            coverage_type=CoverageType.method,
                        ),
                    )

        report_builder_session.append(_file)

    return report_builder_session.output_report()


def _location_to_int(location: dict) -> int | None:
    if "loc" in location:
        location = location["loc"]

    if location.get("skip"):
        return None

    elif location["start"].get("line", 0) == 0:
        return None

    return int(location["start"]["line"])


def _jscoverage_eval_partial(partial):
    return [
        partial["position"],
        partial["position"] + partial["nodeLength"],
        Fraction(
            "{0}/2".format(
                (1 if partial["evalTrue"] else 0) + (1 if partial["evalFalse"] else 0)
            )
        ),
        # It seems like the above line on Python2 would make something in `partials_to_line` always return True
    ]


def jscoverage(_file: ReportFile, data: dict, report_builder_session: ReportBuilderSession):
    branches = {ln:  map(_jscoverage_eval_partial, branchData[1:])
            for ln, branchData in must_be_dict(data["branchData"]).items()
        
    }

    for ln, coverage in enumerate(data["lineData"]):
        if coverage is not None:
            partials = branches.get(str(ln))
            if partials:
                partials = list(partials)
                coverage = partials_to_line(partials)
            _file.append(ln, report_builder_session.create_coverage_line(
                filename=_file.name,
                coverage=coverage,
                coverage_type=CoverageType.branch if partials else CoverageType.line,
                partials=partials,
            ))


def from_json(
    report_dict: dict, report_builder_session: ReportBuilderSession
) -> Report:
    enable_partials = read_yaml_field(report_builder_session.current_yaml, ("parsers", "javascript", "enable_partials"), False)
    fix, ignored_lines = (
        report_builder_session.path_fixer,
        report_builder_session.ignored_lines,
    )

    if enable_partials:
        if next(iter(report_dict.items()))[0].endswith(".js"):
            # only javascript is supported ATM
            return next_from_json(report_dict, report_builder_session)

    for filename, data in report_dict.items():
        name = fix(filename)
        if name is None:
            name = fix(filename.replace("lib/", "src/", 1))
            if name is None:
                continue

        _file = report_builder_session.file_class(
            name=name, ignore=ignored_lines.get(name)
        )

        if data.get("data"):
            # why. idk. node is like that.
            data = data["data"]

        if "lineData" in data:
            jscoverage(_file, data, report_builder_session)
            report_builder_session.append(_file)
            continue

        if "linesCovered" in data:
            for ln, coverage in data["linesCovered"].items():
                _file.append(
                    int(ln),
                    report_builder_session.create_coverage_line(
                        filename=name,
                        coverage=coverage,
                        coverage_type=CoverageType.line,
                    ),
                )
            report_builder_session.append(_file)
            continue

        # statements
        for sid, statement in must_be_dict(data.get("statementMap")).items():
            if statement.get("skip") is not True:
                location_int = _location_to_int(statement)
                if location_int:
                    _file.append(
                        location_int,
                        report_builder_session.create_coverage_line(
                            filename=name,
                            coverage=data["s"][sid],
                            coverage_type=CoverageType.line,
                        ),
                    )

        for bid, branch in must_be_dict(data.get("branchMap")).items():
            if branch.get("skip") is not True:
                # [FUTURE] we can record branch positions in the session
                for lid, location in enumerate(branch["locations"]):
                    location_int = _location_to_int(location)
                    if location_int:
                        _file.append(
                            location_int,
                            report_builder_session.create_coverage_line(
                                filename=name,
                                coverage=data["b"][bid][lid],
                                coverage_type=CoverageType.branch,
                            ),
                        )

        for fid, func in must_be_dict(data.get("fnMap")).items():
            if func.get("skip") is not True:
                location_int = _location_to_int(func["loc"])
                if location_int:
                    _file.append(
                        location_int,
                        report_builder_session.create_coverage_line(
                            filename=name,
                            coverage=data["f"][fid],
                            coverage_type=CoverageType.method,
                        ),
                    )

        report_builder_session.append(_file)

    return report_builder_session.output_report()
