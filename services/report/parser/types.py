from io import BytesIO
from typing import Any

from services.report.fixes import get_fixes_from_raw


class ParsedUploadedReportFile(object):
    def __init__(
        self,
        filename: str | None,
        file_contents: bytes,
        labels: list[str] | None = None,
    ):
        self.filename = filename
        self.contents = file_contents
        self.size = len(self.contents)
        self.labels = labels

    def get_first_line(self):
        return BytesIO(self.contents).readline()


class ParsedRawReport(object):
    """
    Parsed raw report parent class

    Attributes
    ----------
    toc
        table of contents, this lists the files relevant to the report,
        i.e. the files contained in the repository
    uploaded_files
        list of class ParsedUploadedReportFile describing uploaded coverage files
    report_fixes
        list of objects describing report_fixes for each file, the format differs between
        legacy and VersionOne parsed raw report
    """

    def __init__(
        self,
        toc: list[str],
        uploaded_files: list[ParsedUploadedReportFile],
        report_fixes: Any,
    ):
        self.toc = toc
        self.uploaded_files = uploaded_files
        self.report_fixes = report_fixes

    def has_report_fixes(self) -> bool:
        return self.report_fixes is not None

    @property
    def size(self):
        return sum(f.size for f in self.uploaded_files)


class LegacyParsedRawReport(ParsedRawReport):
    """
    report_fixes : bytes
    <filename>:<line number>,<line number>,...
    """

    def get_report_fixes(self, path_fixer) -> dict[str, dict[str, Any]]:
        report_fixes = self.report_fixes.decode(errors="replace")
        return get_fixes_from_raw(report_fixes, path_fixer)


class VersionOneParsedRawReport(ParsedRawReport):
    """
    report_fixes : Dict[str, Dict[str, any]]
    {
        <path to file>: {
            eof: int | None
            lines: List[int]
        },
        ...
    }
    """

    def get_report_fixes(self, path_fixer) -> dict[str, dict[str, Any]]:
        return self.report_fixes

    def as_readable(self) -> bytes:
        buffer = b""
        if self.toc:
            for path in self.toc:
                buffer += f"{path}\n".encode()
            buffer += b"<<<<<< network\n\n"
        for file in self.uploaded_files:
            buffer += f"# path={file.filename}\n".encode()
            buffer += file.contents
            buffer += b"\n<<<<<< EOF\n\n"
        return buffer
