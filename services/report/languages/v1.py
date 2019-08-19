from services.report.languages.helpers import list_to_dict

from covreports.resources import Report, ReportFile
from services.yaml import read_yaml_field
from covreports.utils.tuples import ReportLine
from services.report.languages.base import BaseLanguageProcessor


class VOneProcessor(BaseLanguageProcessor):

    def matches_content(self, content, first_line, name):
        return 'coverage' in content or 'RSpec' in content or 'MiniTest' in content

    def process(self, name, content, path_fixer, ignored_lines, sessionid, repo_yaml=None):
        if 'RSpec' in content:
            content = content['RSpec']

        elif 'MiniTest' in content:
            content = content['MiniTest']

        return from_json(
            content, path_fixer, ignored_lines, sessionid,
            read_yaml_field(repo_yaml, ('parsers', 'v1')) or {}
        )


def from_json(json, fix, ignored_lines, sessionid, config):
    if type(json['coverage']) is dict:
        # messages = json.get('messages', {})
        report = Report()
        for fn, lns in json['coverage'].items():
            fn = fix(fn)
            if fn is None:
                continue

            lns = list_to_dict(lns)
            if lns:
                _file = ReportFile(fn, ignore=ignored_lines.get(fn))
                for ln, cov in lns.items():
                    if int(ln) > 0:
                        if isinstance(cov, str):
                            try:
                                int(cov)
                            except Exception:
                                pass
                            else:
                                cov = int(cov)

                        # message = messages.get(fn, {}).get(ln)
                        _file[int(ln)] = ReportLine(coverage=cov,
                                                    type='b' if type(cov) in (str, bool) else None,
                                                    sessions=[[sessionid, cov]],
                                                    messages=None)

                report.append(_file)

        return report
