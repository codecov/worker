from collections import defaultdict

from shared.reports.resources import Report, ReportFile
from shared.reports.types import ReportLine
from timestring import Date

from helpers.exceptions import ReportExpiredException
from services.report.languages.base import BaseLanguageProcessor
from services.yaml import read_yaml_field


class JacocoProcessor(BaseLanguageProcessor):
    def matches_content(self, content, first_line, name):
        return bool(content.tag == "report")

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml):
        return from_xml(content, path_fixer, ignored_lines, sessionid, repo_yaml)


def from_xml(xml, fix, ignored_lines, sessionid, yaml):
    """
    nr = line number
    mi = missed instructions
    ci = covered instructions
    mb = missed branches
    cb = covered branches
    """
    if read_yaml_field(yaml, ("codecov", "max_report_age"), "12h ago"):
        try:
            timestamp = next(xml.iter("sessioninfo")).get("start")
            if timestamp and Date(timestamp) < read_yaml_field(
                yaml, ("codecov", "max_report_age"), "12h ago"
            ):
                # report expired over 12 hours ago
                raise ReportExpiredException("Jacoco report expired %s" % timestamp)

        except StopIteration:
            pass

    report = Report()

    project = xml.attrib.get("name", "")
    project = "" if " " in project else project.strip("/")

    def try_to_fix_path(path):
        if project:
            # project/package/path
            filename = fix("%s/%s" % (project, path))
            if filename:
                return filename

            # project/src/main/java/package/path
            filename = fix("%s/src/main/java/%s" % (project, path))
            if filename:
                return filename

        # package/path
        return fix(path)

    for package in xml.iter("package"):
        base_name = package.attrib["name"]

        file_method_complixity = defaultdict(dict)
        # Classes complexity
        for _class in package.iter("class"):
            class_name = _class.attrib["name"]
            if "$" not in class_name:
                method_complixity = file_method_complixity[class_name]
                # Method Complexity
                for method in _class.iter("method"):
                    ln = int(method.attrib.get("line", 0))
                    if ln > 0:
                        for counter in method.iter("counter"):
                            if counter.attrib["type"] == "COMPLEXITY":
                                m = int(counter.attrib["missed"])
                                c = int(counter.attrib["covered"])
                                method_complixity[ln] = (c, m + c)
                                break

        # Statements
        for source in package.iter("sourcefile"):
            source_name = "%s/%s" % (base_name, source.attrib["name"])
            filename = try_to_fix_path(source_name)
            if filename is None:
                continue

            method_complixity = file_method_complixity[source_name.split(".")[0]]

            _file = ReportFile(filename, ignore=ignored_lines.get(filename))

            for line in source.iter("line"):
                line = line.attrib
                if line["mb"] != "0":
                    cov = "%s/%s" % (line["cb"], int(line["mb"]) + int(line["cb"]))
                    _type = "b"

                elif line["cb"] != "0":
                    cov = "%s/%s" % (line["cb"], line["cb"])
                    _type = "b"

                else:
                    cov = int(line["ci"])
                    _type = None

                ln = int(line["nr"])
                complexity = method_complixity.get(ln)
                # add line to file
                _file[ln] = ReportLine.create(
                    coverage=cov,
                    type="m" if complexity is not None else _type,
                    sessions=[[sessionid, cov, None, None, complexity]],
                    complexity=complexity,
                )

            # append file to report
            report.append(_file)

    return report
