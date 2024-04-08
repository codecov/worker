import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import List, Mapping, Sequence, Tuple

from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml
from sqlalchemy import desc

from database.enums import ReportType
from database.models import Commit, CommitReport, RepositoryFlag, TestInstance, Upload
from services.report import BaseReportService
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.urls import get_pull_url

log = logging.getLogger(__name__)


class TestResultsReportService(BaseReportService):
    def __init__(self, current_yaml: UserYaml):
        super().__init__(current_yaml)
        self.flag_dict = None

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
