from io import BytesIO, SEEK_END
from typing import BinaryIO, List, Optional


class ParsedUploadedReportFile(object):
    def __init__(self, filename: Optional[str], file_contents: BinaryIO):
        self.filename = filename
        self.contents = self._strip(file_contents)
        self.size = len(self.contents)

    @property
    def file_contents(self):
        return BytesIO(self.contents)

    def get_first_line(self):
        return self.file_contents.readline()

    @classmethod
    def _strip(cls, file_contents: BinaryIO) -> bytes:
        """Strips the file in the same way that .strip() does

        This should be funcitionally similar to calling file_contents.getvalue().strip

        The only thing we are doing different is to try to benefit from the fact that BytesIO
            is a mutable structure (unlike `bytes`), so we can rstrip it without having to make
            full copies of it

        On memory tests, this lead to peak memory from n * file_size to (n - 1) * file_size,
            because rstrip would almost always have to create a copy of the original bytes. It
            wouldn't create a full copy if the result was exactly the same as the original,
            but those files almost always would have a trailing line break

        Args:
            file_contents (BinaryIO): The file contents we want to strip

        Returns:
            bytes: Description
        """
        current_index = -10
        while True:
            file_contents.seek(current_index, SEEK_END)
            v = file_contents.read()
            if v == v.rstrip():
                # lstrips is not easily doable on BytesIO
                # but on the other hand, it doesn't usually makes copy of the content anyway
                # since there are not as many starting line breaks
                return file_contents.getvalue().lstrip()
            value_to_trim = len(v) - len(v.rstrip())
            file_contents.seek(-value_to_trim, SEEK_END)
            file_contents.truncate()


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
            separator_lines_found = [
                x for x in cls.separator_lines if x in current_line
            ]
            if separator_lines_found:
                separator_line_used = separator_lines_found[0]
                remaining_content = current_line.split(separator_line_used)[0]
                if remaining_content:
                    current_section_information["contents"].write(remaining_content)
                current_section_information["footer"] = separator_line_used
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
