import logging
from dataclasses import dataclass
from typing import Optional

import sentry_sdk

from app import celery_app
from database.engine import Session
from database.models import (
    Branch,
    Commit,
    CommitError,
    CommitNotification,
    CommitReport,
    CompareCommit,
    CompareFlag,
    LabelAnalysisRequest,
    Pull,
    ReportDetails,
    ReportLevelTotals,
    ReportResults,
    Repository,
    RepositoryFlag,
    StaticAnalysisSingleFileSnapshot,
    StaticAnalysisSuite,
    StaticAnalysisSuiteFilepath,
    Upload,
    UploadError,
    UploadLevelTotals,
    uploadflagmembership,
)
from services.archive import ArchiveService
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


@dataclass
class FlushRepoTaskReturnType(object):
    error: Optional[str] = None
    deleted_commits_count: int = 0
    delete_branches_count: int = 0
    deleted_pulls_count: int = 0
    deleted_archives_count: int = 0


class FlushRepoTask(BaseCodecovTask, name="app.tasks.flush_repo.FlushRepo"):
    @sentry_sdk.trace
    def _delete_archive(self, repo: Repository) -> int:
        archive_service = ArchiveService(repo)
        deleted_archives = archive_service.delete_repo_files()
        log.info(
            "Deleted archives from storage",
            extra=dict(repoid=repo.repoid, deleted_archives_count=deleted_archives),
        )
        return deleted_archives

    @sentry_sdk.trace
    def _delete_comparisons(self, db_session: Session, commit_ids, repoid: int) -> None:
        commit_comparison_ids = db_session.query(CompareCommit.id_).filter(
            CompareCommit.base_commit_id.in_(commit_ids)
            | CompareCommit.compare_commit_id.in_(commit_ids)
        )
        db_session.query(CompareFlag).filter(
            CompareFlag.commit_comparison_id.in_(commit_comparison_ids)
        ).delete(synchronize_session=False)
        db_session.commit()
        db_session.query(CompareCommit).filter(
            CompareCommit.base_commit_id.in_(commit_ids)
            | CompareCommit.compare_commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.commit()
        log.info("Deleted comparisons", extra=dict(repoid=repoid))

    @sentry_sdk.trace
    def _delete_reports(self, db_session: Session, report_ids, repoid: int):
        db_session.query(ReportDetails).filter(
            ReportDetails.report_id.in_(report_ids)
        ).delete(synchronize_session=False)
        db_session.query(ReportLevelTotals).filter(
            ReportLevelTotals.report_id.in_(report_ids)
        ).delete(synchronize_session=False)
        db_session.query(ReportResults).filter(
            ReportResults.report_id.in_(report_ids)
        ).delete(synchronize_session=False)
        db_session.commit()
        log.info("Deleted reports", extra=dict(repoid=repoid))

    @sentry_sdk.trace
    def _delete_uploads(self, db_session: Session, report_ids, repoid: int):
        # uploads
        upload_ids = db_session.query(Upload.id_).filter(
            Upload.report_id.in_(report_ids)
        )
        db_session.query(UploadError).filter(
            UploadError.upload_id.in_(upload_ids)
        ).delete(synchronize_session=False)
        db_session.query(UploadLevelTotals).filter(
            UploadLevelTotals.upload_id.in_(upload_ids)
        ).delete(synchronize_session=False)
        db_session.query(uploadflagmembership).filter(
            uploadflagmembership.c.upload_id.in_(upload_ids)
        ).delete(synchronize_session=False)
        db_session.query(Upload).filter(Upload.report_id.in_(report_ids)).delete(
            synchronize_session=False
        )
        db_session.commit()
        log.info("Deleted uploads", extra=dict(repoid=repoid))

    @sentry_sdk.trace
    def _delete_commit_details(self, db_session: Session, commit_ids, repoid: int):
        db_session.query(CommitReport).filter(
            CommitReport.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.query(RepositoryFlag).filter_by(repository_id=repoid).delete()
        db_session.commit()
        db_session.query(CommitError).filter(
            CommitError.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.query(CommitNotification).filter(
            CommitNotification.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.commit()
        log.info("Deleted commit details", extra=dict(repoid=repoid))

    @sentry_sdk.trace
    def _delete_static_analysis(self, db_session: Session, commit_ids, repoid: int):
        db_session.query(StaticAnalysisSuite).filter(
            StaticAnalysisSuite.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        snapshot_ids = db_session.query(StaticAnalysisSingleFileSnapshot.id_).filter_by(
            repository_id=repoid
        )
        db_session.query(StaticAnalysisSuiteFilepath).filter(
            StaticAnalysisSuiteFilepath.file_snapshot_id.in_(snapshot_ids)
        ).delete(synchronize_session=False)
        db_session.query(StaticAnalysisSingleFileSnapshot).filter_by(
            repository_id=repoid
        ).delete()
        db_session.commit()
        log.info("Deleted static analysis info", extra=dict(repoid=repoid))

    @sentry_sdk.trace
    def _delete_label_analysis(self, db_session: Session, commit_ids, repoid: int):
        db_session.query(LabelAnalysisRequest).filter(
            LabelAnalysisRequest.base_commit_id.in_(commit_ids)
            | LabelAnalysisRequest.head_commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.commit()
        log.info("Deleted label analysis info", extra=dict(repoid=repoid))

    @sentry_sdk.trace
    def _delete_commits(self, db_session: Session, repoid: int) -> int:
        delete_count = (
            db_session.query(Commit)
            .filter_by(repoid=repoid)
            .delete(synchronize_session=False)
        )
        db_session.commit()

        log.info(
            "Deleted commits", extra=dict(repoid=repoid, deleted_count=delete_count)
        )
        return delete_count

    @sentry_sdk.trace
    def _delete_branches(self, db_session: Session, repoid: int) -> int:
        deleted_branches = db_session.query(Branch).filter_by(repoid=repoid).delete()
        db_session.commit()
        log.info("Deleted branches", extra=dict(repoid=repoid))
        return deleted_branches

    @sentry_sdk.trace
    def _delete_pulls(self, db_session: Session, repoid: int) -> int:
        deleted_pulls = db_session.query(Pull).filter_by(repoid=repoid).delete()
        db_session.commit()
        log.info("Deleted pulls", extra=dict(repoid=repoid))
        return deleted_pulls

    @sentry_sdk.trace
    def run_impl(
        self, db_session: Session, *, repoid: int, **kwargs
    ) -> FlushRepoTaskReturnType:
        log.info("Deleting repo contents", extra=dict(repoid=repoid))
        repo = db_session.query(Repository).filter_by(repoid=repoid).first()
        if repo is None:
            log.exception("Repo not found", extra=dict(repoid=repoid))
            return FlushRepoTaskReturnType(error="repo not found")

        deleted_archives = self._delete_archive(repo)
        commit_ids = db_session.query(Commit.id_).filter_by(repoid=repo.repoid)
        self._delete_comparisons(db_session, commit_ids, repoid)

        report_ids = db_session.query(CommitReport.id_).filter(
            CommitReport.commit_id.in_(commit_ids)
        )
        self._delete_reports(db_session, report_ids, repoid)
        self._delete_uploads(db_session, report_ids, repoid)

        self._delete_commit_details(db_session, commit_ids, repoid)

        # TODO: Component comparison

        self._delete_static_analysis(db_session, commit_ids, repoid)

        deleted_commits = self._delete_commits(db_session, repoid)
        deleted_branches = self._delete_branches(db_session, repoid)
        deleted_pulls = self._delete_pulls(db_session, repoid)
        repo.yaml = None
        return FlushRepoTaskReturnType(
            deleted_archives_count=deleted_archives,
            deleted_commits_count=deleted_commits,
            delete_branches_count=deleted_branches,
            deleted_pulls_count=deleted_pulls,
        )


FlushRepo = celery_app.register_task(FlushRepoTask())
flush_repo = celery_app.tasks[FlushRepo.name]
