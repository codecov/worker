from io import BytesIO
from typing import BinaryIO, List, Optional


class ParsedUploadedReportFile(object):
    def __init__(self, filename: Optional[str], file_contents: BinaryIO):
        self.filename = filename
        self.contents = file_contents.getvalue().strip()

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
    def parse_raw_report_from_bytes(cls, raw_report: bytes) -> ParsedRawReport:
        return cls.parse_raw_report_from_io(BytesIO(raw_report))

    @classmethod
    def parse_raw_report_from_io(cls, raw_report: BinaryIO) -> ParsedRawReport:
        sections = []
        current_section_information = {
            "contents": BytesIO(),
            "filename": None,
            "footer": None,
        }
        for current_line in raw_report:
            if current_line.rstrip() in cls.separator_lines:
                current_section_information["footer"] = current_line.rstrip()
                current_section_information["contents"].seek(0)
                sections.append(current_section_information)
                current_section_information = {
                    "contents": BytesIO(),
                    "filename": None,
                    "footer": None,
                }
            elif current_line.startswith(b"# path="):
                current_section_information["filename"] = (
                    current_line.split(b"# path=")[1].decode().strip()
                )
            else:
                current_section_information["contents"].write(current_line)
        if current_section_information["contents"].tell() > 0:
            current_section_information["contents"].seek(0)
            sections.append(current_section_information)
        return cls._generate_parsed_report_from_sections(sections)

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
