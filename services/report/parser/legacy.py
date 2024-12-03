import string
from io import BytesIO

import sentry_sdk

from services.path_fixer.fixpaths import clean_toc
from services.report.parser.types import LegacyParsedRawReport, ParsedUploadedReportFile


class LegacyReportParser(object):
    network_separator = b"<<<<<< network"
    env_separator = b"<<<<<< ENV"
    eof_separator = b"<<<<<< EOF"
    ignore_from_now_on_marker = b"==FROMNOWONIGNOREDBYCODECOV==>>>"

    separator_lines = [network_separator, env_separator, eof_separator]

    def _find_place_to_cut(self, raw_report: bytes):
        """Finds the locations of all separators in the report, as listed above.

        Args:
            raw_report (bytes): the raw_report to parse

        Yields:
            tuple: tuple in the format (separator_location, separator)
        """
        common_base = b"<<<<<<"
        starting_point = 0
        while 0 <= starting_point <= len(raw_report):
            next_place = raw_report.find(common_base, starting_point)
            if next_place >= 0:
                starting_point = next_place + 1
                for separator in self.separator_lines:
                    w = raw_report.find(
                        separator, next_place, next_place + len(separator)
                    )
                    if w >= 0:
                        yield w, separator
                        starting_point = next_place + len(separator)
            else:
                return

    def _get_sections_to_cut(self, raw_report: bytes):
        """Finds which are the sections to cut when parsing `raw_report`.
            It yields, for each section, where it starts, ends and what separator it uses

        Args:
            raw_report (bytes): the raw_report to parse

        Yields:
            tuple: tuple in the format (start_index, end_index, separator used)
        """
        places_to_cut = sorted(self._find_place_to_cut(raw_report))
        if places_to_cut:
            yield (0, places_to_cut[0][0], places_to_cut[0][1])
            for prev, nex in zip(places_to_cut, places_to_cut[1:]):
                yield (prev[0] + len(prev[1]), nex[0], nex[1])
            yield (
                places_to_cut[-1][0] + len(places_to_cut[-1][1]),
                len(raw_report),
                None,
            )
        else:
            yield (0, len(raw_report), None)

    def cut_sections(self, raw_report: bytes):
        """Cuts `raw_report` into the sections that we recognize in a report

        This function takes the proper steps to find all the relevant sections of a report:
            - toc: the 'network', list of files present on this report
            - uploaded_files: the actual report files
            - report_fixes: the report fixes some languages need

        and splits them, also taking care of 'strip()' them, removing whitespaces,
            as the original logic also does.

        Args:
            raw_report (bytes): the raw_report to parse

        Yields:
            dict: Dicts with contents, filename and footer of each section
        """
        whitespaces = set(string.whitespace.encode())
        sections = self._get_sections_to_cut(raw_report)
        for start, end, separator in sections:
            i_start, i_end = start, end
            while i_start < i_end and raw_report[i_start] in whitespaces:
                i_start += 1
            while i_start < i_end and raw_report[i_end - 1] in whitespaces:
                i_end -= 1
            if i_start < i_end:
                filename = None
                if raw_report[i_start : i_start + len(b"# path=")] == b"# path=":
                    content = BytesIO(raw_report)
                    content.seek(i_start)
                    first_line = next(iter(content))
                    filename = first_line.split(b"# path=")[1].decode().strip()
                    i_start = i_start + len(first_line)
                    while i_start < i_end and raw_report[i_start] in whitespaces:
                        i_start += 1
                yield {
                    "filename": filename,
                    "contents": raw_report[i_start:i_end],
                    "footer": separator,
                }

    @sentry_sdk.trace
    def parse_raw_report_from_bytes(self, raw_report: bytes) -> LegacyParsedRawReport:
        raw_report, _, _compat_report_str = raw_report.partition(
            self.ignore_from_now_on_marker
        )
        sections = self.cut_sections(raw_report)
        return self._generate_parsed_report_from_sections(sections)

    def _generate_parsed_report_from_sections(self, sections):
        uploaded_files = []
        toc = None
        report_fixes = None
        for sect in sections:
            if sect["footer"] == self.network_separator:
                toc = clean_toc(sect["contents"].decode(errors="replace").strip())
            elif sect["footer"] == self.env_separator:
                pass
            elif sect["filename"] == "fixes":
                report_fixes = sect["contents"]
            else:
                file = ParsedUploadedReportFile(
                    filename=sect["filename"], file_contents=sect["contents"]
                )
                uploaded_files.append(file)

        return LegacyParsedRawReport(
            toc=toc or [],
            uploaded_files=uploaded_files,
            report_fixes=report_fixes,
        )
