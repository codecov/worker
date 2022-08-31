import typing
from collections import defaultdict
from fractions import Fraction

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from shared.utils.merge import partials_to_line

from services.report.languages.base import BaseLanguageProcessor
from services.report.report_builder import ReportBuilder
from services.yaml import read_yaml_field


class NodeProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        if not isinstance(content, dict):
            return False
        return all(isinstance(data, dict) for data in content.values())

    def process(
        self, name: str, content: typing.Any, report_builder: ReportBuilder
    ) -> Report:
        path_fixer, ignored_lines, sessionid, repo_yaml = (
            report_builder.path_fixer,
            report_builder.ignored_lines,
            report_builder.sessionid,
            report_builder.repo_yaml,
        )
        config = read_yaml_field(repo_yaml, ("parsers", "javascript")) or {}
        return from_json(content, path_fixer, ignored_lines, sessionid, config)


def get_line_coverage(location, cov, line_type):
    if location.get("skip"):
        return None, None, None

    sl, sc, el, ec = get_location(location)

    if not sl or sc + 1 == ec:
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
    if type(value) is not dict:
        return {}
    else:
        return value


def next_from_json(report_dict, fix, ignored_lines, sessionid, config):
    report = Report()
    for filename, data in report_dict.items():
        name = fix(filename)
        if name is None:
            name = fix(filename.replace("lib/", "src/", 1))
            if name is None:
                continue

        _file = ReportFile(name, ignore=ignored_lines.get(name))

        if "lineData" in data:
            jscoverage(_file, data, sessionid)
            report.append(_file)
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
                            ReportLine.create(
                                cov, "b", [[sessionid, cov, branches, partials]]
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
                    ln, ReportLine.create(cov, None, [[sessionid, cov, None, partials]])
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
                                _file[sl] = ReportLine.create(
                                    cov, "b", [[sessionid, cov, mb, partials]]
                                )
                                continue

                            sc, ec = sc + 4, cur_partials[0][0] - 2
                            isc, iec, icov = inline_part
                            if sc > ec:
                                cur_partials.append(
                                    [cur_partials[-1][1] + 2, iec, icov]
                                )
                                _file[sl] = ReportLine.create(
                                    cov, "b", [[sessionid, cov, mb, cur_partials]]
                                )
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

                                _file[sl] = ReportLine.create(
                                    cov,
                                    "b",
                                    [
                                        [
                                            sessionid,
                                            cov,
                                            mb,
                                            sorted(partials, key=lambda p: p[0]),
                                        ]
                                    ],
                                )

                        else:
                            # if ( exp && expr )
                            # change to branch
                            _file[sl] = ReportLine.create(
                                cov,
                                "b",
                                [[sessionid, cov, mb, _file[sl].sessions[-1].partials]],
                            )

                    else:
                        _file.append(
                            sl,
                            ReportLine.create(cov, "b", [[sessionid, cov, mb, None]]),
                        )

        for fid, func in must_be_dict(data["fnMap"]).items():
            if func.get("skip") is not True:
                ln, cov, partials = get_line_coverage(func, data["f"][fid], "m")
                if ln:
                    _file.append(
                        ln, ReportLine.create(cov, "m", [[sessionid, cov, None, None]])
                    )

        report.append(_file)

    return report


def _location_to_lines(_file, location, cov, _type, sessionid):
    if "loc" in location:
        location = location["loc"]

    if location.get("skip"):
        return

    elif location["start"].get("line", 0) == 0:
        return

    _file.append(
        int(location["start"]["line"]),
        ReportLine.create(cov, _type, [[sessionid, cov]], None),
    )


def _jscoverage_eval_partial(partial):
    return [
        partial["position"],
        partial["position"] + partial["nodeLength"],
        Fraction(
            "{0}/2".format(
                (1 if partial["evalTrue"] else 0) + (1 if partial["evalFalse"] else 0)
            )
        )
        # It seems like the above line on Python2 would make something in `partials_to_line` always return True
    ]


def jscoverage(_file, data, sessionid):
    branches = dict(
        (
            (ln, map(_jscoverage_eval_partial, branchData[1:]))
            for ln, branchData in must_be_dict(data["branchData"]).items()
        )
    )

    for ln, coverage in enumerate(data["lineData"]):
        if coverage is not None:
            partials = branches.get(str(ln))
            if partials:
                partials = list(partials)
                coverage = partials_to_line(partials)
            _file[ln] = ReportLine.create(
                coverage,
                "b" if partials else None,
                [[sessionid, coverage, None, partials]],
            )


def from_json(report_dict, fix, ignored_lines, sessionid, config):
    if config.get("enable_partials", False):
        if next(iter(report_dict.items()))[0].endswith(".js"):
            # only javascript is supported ATM
            return next_from_json(report_dict, fix, ignored_lines, sessionid, config)

    report = Report()
    for filename, data in report_dict.items():
        name = fix(filename)
        if name is None:
            name = fix(filename.replace("lib/", "src/", 1))
            if name is None:
                continue

        _file = ReportFile(name, ignore=ignored_lines.get(name))

        if data.get("data"):
            # why. idk. node is like that.
            data = data["data"]

        if "lineData" in data:
            jscoverage(_file, data, sessionid)
            report.append(_file)
            continue

        if "linesCovered" in data:
            for ln, coverage in data["linesCovered"].items():
                _file.append(
                    int(ln),
                    ReportLine.create(
                        coverage=coverage, sessions=[[sessionid, coverage]]
                    ),
                )
            report.append(_file)
            continue

        # statements
        for sid, statement in must_be_dict(data.get("statementMap")).items():
            if statement.get("skip") is not True:
                _location_to_lines(_file, statement, data["s"][sid], None, sessionid)

        for bid, branch in must_be_dict(data.get("branchMap")).items():
            if branch.get("skip") is not True:
                # [FUTURE] we can record branch positions in the session
                for lid, location in enumerate(branch["locations"]):
                    _location_to_lines(
                        _file, location, data["b"][bid][lid], "b", sessionid
                    )

        for fid, func in must_be_dict(data.get("fnMap")).items():
            if func.get("skip") is not True:
                _location_to_lines(_file, func["loc"], data["f"][fid], "m", sessionid)

        report.append(_file)

    return report
