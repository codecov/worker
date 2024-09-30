import logging

from asgiref.sync import async_to_sync
from shared.reports.readonly import ReadOnlyReport
from shared.yaml import UserYaml

from app import celery_app
from database.enums import ReportType
from database.models import Commit, Pull
from database.models.reports import CommitReport, ReportResults
from helpers.exceptions import RepositoryWithoutValidBotError
from helpers.github_installation import get_installation_name_for_owner_for_task
from services.comparison import ComparisonProxy
from services.comparison.types import Comparison, FullCommit
from services.notification.notifiers.status.patch import PatchStatusNotifier
from services.report import ReportService
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.yaml import get_current_yaml
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class SaveReportResultsTask(
    BaseCodecovTask, name="app.tasks.reports.save_report_results"
):
    def run_impl(
        self, db_session, *, repoid, commitid, report_code, current_yaml, **kwargs
    ):
        commit = self.fetch_commit(db_session, repoid, commitid)

        try:
            installation_name_to_use = get_installation_name_for_owner_for_task(
                self.name, commit.repository.owner
            )
            repository_service = get_repo_provider_service(
                commit.repository, installation_name_to_use=installation_name_to_use
            )
        except RepositoryWithoutValidBotError:
            return {
                "report_results_saved": False,
                "reason": "repository without valid bot",
            }

        current_yaml = self.fetch_yaml_dict(current_yaml, commit, repository_service)
        enriched_pull = async_to_sync(
            fetch_and_update_pull_request_information_from_commit
        )(repository_service, commit, current_yaml)
        base_commit = self.fetch_base_commit(commit, enriched_pull)
        base_report, head_report = self.fetch_base_and_head_reports(
            current_yaml, commit, base_commit, report_code
        )

        if enriched_pull and enriched_pull.database_pull:
            patch_coverage_base_commitid = enriched_pull.database_pull.base
        else:
            patch_coverage_base_commitid = base_commit.commitid if base_commit else None

        if head_report is None:
            log.warning(
                "Not saving report results because no head report found.",
                extra=dict(repoid=repoid, commit_id=commitid),
            )
            return {"report_results_saved": False, "reason": "No head report found."}

        comparison = ComparisonProxy(
            Comparison(
                head=FullCommit(commit=commit, report=head_report),
                enriched_pull=enriched_pull,
                project_coverage_base=FullCommit(
                    commit=base_commit, report=base_report
                ),
                patch_coverage_base_commitid=patch_coverage_base_commitid,
            )
        )

        notifier = PatchStatusNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml=current_yaml,
        )
        result = notifier.build_payload(comparison)
        report = self.fetch_report(commit, report_code)
        log.info(
            "Saving report results into the db",
            extra=dict(repoid=repoid, commitid=commitid, report_id=report.id),
        )
        self.save_results_into_db(result, report)
        return {"report_results_saved": True, "reason": "success"}

    def fetch_base_and_head_reports(
        self, current_yaml, commit, base_commit, report_code
    ):
        report_service = ReportService(current_yaml)
        if base_commit is not None:
            base_report = report_service.get_existing_report_for_commit(
                base_commit, report_class=ReadOnlyReport
            )
        else:
            base_report = None
        head_report = report_service.get_existing_report_for_commit(
            commit, report_class=ReadOnlyReport, report_code=report_code
        )

        return base_report, head_report

    def fetch_base_commit(self, commit, enriched_pull):
        if enriched_pull and enriched_pull.database_pull:
            pull = enriched_pull.database_pull
            base_commit = self.fetch_pull_request_base(pull)
        else:
            pull = None
            base_commit = self.fetch_parent(commit)
        return base_commit

    def fetch_yaml_dict(self, current_yaml, commit, repository_service):
        if current_yaml is None:
            current_yaml = async_to_sync(get_current_yaml)(commit, repository_service)
        else:
            current_yaml = UserYaml.from_dict(current_yaml)
        return current_yaml

    def fetch_commit(self, db_session, repoid, commitid) -> Commit | None:
        commits_query = db_session.query(Commit).filter(
            Commit.repoid == repoid, Commit.commitid == commitid
        )
        commit = commits_query.first()
        return commit

    def save_results_into_db(self, result, report):
        db_session = report.get_db_session()
        report_results = (
            db_session.query(ReportResults)
            .filter(ReportResults.report == report)
            .first()
        )
        report_results.state = "Completed"
        report_results.result = result
        db_session.add(report_results)
        db_session.flush()

    def fetch_report(self, commit: Commit, report_code: str) -> CommitReport:
        db_session = commit.get_db_session()
        return (
            db_session.query(CommitReport)
            .filter_by(commit_id=commit.id_, code=report_code)
            .filter(
                (CommitReport.report_type == None)  # noqa: E711
                | (CommitReport.report_type == ReportType.COVERAGE.value)
            )
            .first()
        )

    def fetch_pull_request_base(self, pull: Pull) -> Commit:
        return pull.get_comparedto_commit()

    def fetch_parent(self, commit):
        db_session = commit.get_db_session()
        return (
            db_session.query(Commit)
            .filter_by(commitid=commit.parent_commit_id, repoid=commit.repoid)
            .first()
        )


RegisteredSaveReportResultsTask = celery_app.register_task(SaveReportResultsTask())
save_report_results_task = celery_app.tasks[RegisteredSaveReportResultsTask.name]
