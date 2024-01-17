import logging
from hashlib import sha256
from typing import Mapping, Sequence

from shared.torngit.exceptions import TorngitClientError
from test_results_parser import Outcome, Testrun

from database.enums import ReportType
from database.models import Commit, CommitReport, RepositoryFlag, Upload
from services.report import BaseReportService
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)

log = logging.getLogger(__name__)


class TestResultsReportService(BaseReportService):
    async def initialize_and_save_report(
        self, commit: Commit, report_code: str = None
    ) -> CommitReport:
        db_session = commit.get_db_session()
        current_report_row = (
            db_session.query(CommitReport)
            .filter_by(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.TEST_RESULTS.value,
            )
            .first()
        )
        if not current_report_row:
            # This happens if the commit report is being created for the first time
            # or backfilled
            current_report_row = CommitReport(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.TEST_RESULTS.value,
            )
            db_session.add(current_report_row)
            db_session.flush()

        return current_report_row

    # support flags in test results
    def create_report_upload(
        self, normalized_arguments: Mapping[str, str], commit_report: CommitReport
    ) -> Upload:
        upload = super().create_report_upload(normalized_arguments, commit_report)
        flags = normalized_arguments.get("flags")
        flags = flags or []
        self._attach_flags_to_upload(upload, flags)
        return upload

    def _attach_flags_to_upload(self, upload: Upload, flag_names: Sequence[str]):
        """Internal function that manages creating the proper `RepositoryFlag`s and attach the sessions to them

        Args:
            upload (Upload): Description
            flag_names (Sequence[str]): Description

        Returns:
            TYPE: Description
        """
        all_flags = []
        db_session = upload.get_db_session()
        repoid = upload.report.commit.repoid
        for individual_flag in flag_names:
            existing_flag = (
                db_session.query(RepositoryFlag)
                .filter_by(repository_id=repoid, flag_name=individual_flag)
                .first()
            )
            if not existing_flag:
                existing_flag = RepositoryFlag(
                    repository_id=repoid, flag_name=individual_flag
                )
                db_session.add(existing_flag)
                db_session.flush()
            upload.flags.append(existing_flag)
            db_session.flush()
            all_flags.append(existing_flag)
        return all_flags


def generate_env(flag_names):
    return sha256((" ".join(sorted(flag_names))).encode("utf-8")).hexdigest()


def generate_test_id(repoid, testsuite, name, env):
    return sha256(
        (" ".join([str(x) for x in [repoid, testsuite, name, env]])).encode("utf-8")
    ).hexdigest()
