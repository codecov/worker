from services.path_fixer import PathFixer
from services.report.report_builder import ReportBuilder, ReportBuilderSession


def create_report_builder_session(
    path_fixer: PathFixer | None = None,
    filename: str = "filename",
    current_yaml: dict | None = None,
    should_use_label_index: bool = False,
) -> ReportBuilderSession:
    def fixes(filename, bases_to_try=None):
        return filename

    report_builder = ReportBuilder(
        path_fixer=path_fixer or fixes,
        ignored_lines={},
        sessionid=0,
        current_yaml=current_yaml,
        should_use_label_index=should_use_label_index,
    )
    return report_builder.create_report_builder_session(filename)
