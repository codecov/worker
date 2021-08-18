import string
from io import BytesIO
from typing import BinaryIO, List, Optional

from helpers.metrics import metrics


class ParsedUploadedReportFile(object):
    def __init__(self, filename: Optional[str], file_contents: BinaryIO):
        self.filename = filename
        self.contents = file_contents.getvalue()
        self.size = len(self.contents)

    @property
    def file_contents(self):
        return BytesIO(self.contents)

    def get_first_line(self):
        return self.file_contents.readline()


class ParsedRawReport(object):
    def __init__(
        self,
        toc: Optional[BinaryIO],
        env: Optional[BinaryIO],
        uploaded_files: List[ParsedUploadedReportFile],
        path_fixes: Optional[BinaryIO],
    ):
        self.toc = toc
        self.env = env
        self.uploaded_files = uploaded_files
        self.path_fixes = path_fixes

    def has_toc(self) -> bool:
        return self.toc is not None

    def has_env(self) -> bool:
        return self.env is not None

    def has_path_fixes(self) -> bool:
        return self.path_fixes is not None

    @property
    def size(self):
        return sum(f.size for f in self.uploaded_files)


class RawReportParser(object):

    network_separator = b"<<<<<< network"
    env_separator = b"<<<<<< ENV"
    eof_separator = b"<<<<<< EOF"

    separator_lines = [
        network_separator,
        env_separator,
        eof_separator,
    ]

    @classmethod
    def _find_place_to_cut(cls, raw_report: bytes):
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
                for separator in cls.separator_lines:
                    w = raw_report.find(
                        separator, next_place, next_place + len(separator)
                    )
                    if w >= 0:
                        yield w, separator
                        starting_point = next_place + len(separator)
            else:
                return

    @classmethod
    def _get_sections_to_cut(cls, raw_report: bytes):
        """Finds which are the sections to cut when parsing `raw_report`.
            It yields, for each section, where it starts, ends and what separator it uses

        Args:
            raw_report (bytes): the raw_report to parse

        Yields:
            tuple: tuple in the format (start_index, end_index, separator used)
        """
        places_to_cut = sorted(cls._find_place_to_cut(raw_report))
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

    @classmethod
    def cut_sections(cls, raw_report: bytes):
        """Cuts `raw_report` into the sections that we recognize in a report

        This function takes the proper steps to find all the relevant sections of a report:
            - toc: the 'network', list of files present on this report
            - env: the envvars the user set on the upload
            - uploaded_files: the actual report files
            - path_fixes: the patfixes some languages need

        and splits them, also taking care of 'strip()' them, removing whitespaces,
            as the original logic also does.

        Args:
            raw_report (bytes): the raw_report to parse

        Yields:
            dict: Dicts with contents, filename and footer of each section
        """
        whitespaces = set(string.whitespace.encode())
        sections = cls._get_sections_to_cut(raw_report)
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
                    "contents": BytesIO(raw_report[i_start:i_end]),
                    "filename": filename,
                    "footer": separator,
                }

    @classmethod
    @metrics.timer("services.report.parser.parse_raw_report_from_bytes")
    def parse_raw_report_from_bytes(cls, raw_report: bytes) -> ParsedRawReport:
        sections = cls.cut_sections(raw_report)
        return cls._generate_parsed_report_from_sections(sections)

    @classmethod
    def parse_raw_report_from_io(cls, raw_report: BinaryIO) -> ParsedRawReport:
        return cls.parse_raw_report_from_bytes(raw_report.getvalue())

    @classmethod
    def _generate_parsed_report_from_sections(cls, sections):
        uploaded_files = []
        toc_section = None
        env_section = None
        path_fixes_section = None
        for sect in sections:
            if sect["footer"] == cls.network_separator:
                toc_section = sect["contents"]
            elif sect["footer"] == cls.env_separator:
                env_section = sect["contents"]
            else:
                if sect["filename"] == "fixes":
                    path_fixes_section = sect["contents"]
                else:
                    uploaded_files.append(
                        ParsedUploadedReportFile(
                            filename=sect.get("filename"),
                            file_contents=sect["contents"],
                        )
                    )
        return ParsedRawReport(
            toc=toc_section,
            env=env_section,
            uploaded_files=uploaded_files,
            path_fixes=path_fixes_section,
        )
