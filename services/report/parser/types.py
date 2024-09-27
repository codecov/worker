from io import BytesIO
from typing import Any, BinaryIO, Dict, List, Optional

from services.path_fixer.fixpaths import clean_toc
from services.report.fixes import get_fixes_from_raw


class ParsedUploadedReportFile(object):
    def __init__(
        self,
        filename: Optional[str],
        file_contents: BinaryIO,
        labels: Optional[List[str]] = None,
    ):
        self.filename = filename
        self.contents = file_contents.getvalue()
        self.size = len(self.contents)
        self.labels = labels

    @property
    def file_contents(self):
        return BytesIO(self.contents)

    def get_first_line(self):
        return self.file_contents.readline()


class ParsedRawReport(object):
    """
    Parsed raw report parent class

    Attributes
    ----------
    toc
        table of contents, this lists the files relevant to the report,
        i.e. the files contained in the repository
    env
        list of env vars in environment of uploader (legacy only)
    uploaded_files
        list of class ParsedUploadedReportFile describing uploaded coverage files
    report_fixes
        list of objects describing report_fixes for each file, the format differs between
        legacy and VersionOne parsed raw report
    """

    def __init__(
        self,
        toc: Optional[BinaryIO],
        env: Optional[BinaryIO],
        uploaded_files: List[ParsedUploadedReportFile],
        report_fixes: Optional[BinaryIO],
    ):
        self.toc = toc
        self.env = env
        self.uploaded_files = uploaded_files
        self.report_fixes = report_fixes

    def has_toc(self) -> bool:
        return self.toc is not None

    def has_env(self) -> bool:
        return self.env is not None

    def has_report_fixes(self) -> bool:
        return self.report_fixes is not None

    @property
    def size(self):
        return sum(f.size for f in self.uploaded_files)

    def content(self) -> BytesIO:
        buffer = BytesIO()
        if self.has_toc():
            for file in self.get_toc():
                buffer.write(f"{file}\n".encode("utf-8"))
            buffer.write(b"<<<<<< network\n\n")
        for file in self.uploaded_files:
            buffer.write(f"# path={file.filename}\n".encode("utf-8"))
            buffer.write(file.contents)
            buffer.write(b"\n<<<<<< EOF\n\n")
        buffer.seek(0)
        return buffer


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

    def get_toc(self) -> List[str]:
        return self.toc

    def get_env(self):
        return self.env

    def get_uploaded_files(self):
        return self.uploaded_files

    def get_report_fixes(self, path_fixer) -> Dict[str, Dict[str, Any]]:
        return self.report_fixes


class LegacyParsedRawReport(ParsedRawReport):
    """
    report_fixes : BinaryIO
    <filename>:<line number>,<line number>,...
    """

    def get_toc(self) -> List[str]:
        toc = self.toc.read().decode(errors="replace").strip()
        toc = clean_toc(toc)
        self.toc.seek(0, 0)
        return toc

    def get_env(self):
        return self.env.read().decode(errors="replace")

    def get_uploaded_files(self):
        return self.uploaded_files

    def get_report_fixes(self, path_fixer) -> Dict[str, Dict[str, Any]]:
        report_fixes = self.report_fixes.read().decode(errors="replace")
        return get_fixes_from_raw(report_fixes, path_fixer)
