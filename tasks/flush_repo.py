import logging

from sqlalchemy import null

from app import celery_app
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


class FlushRepoTask(BaseCodecovTask, name="app.tasks.flush_repo.FlushRepo"):
    async def run_async(self, db_session, *, repoid: int, **kwargs):
        log.info("Deleting repo contents", extra=dict(repoid=repoid))
        repo = db_session.query(Repository).filter_by(repoid=repoid).first()
        archive_service = ArchiveService(repo)
        deleted_archives = archive_service.delete_repo_files()

        commit_ids = db_session.query(Commit.id_).filter_by(repoid=repoid)

        # comparisons
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

        # reports
        report_ids = db_session.query(CommitReport.id_).filter(
            CommitReport.commit_id.in_(commit_ids)
        )
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
        db_session.commit()

        db_session.query(Upload).filter(Upload.report_id.in_(report_ids)).delete(
            synchronize_session=False
        )
        db_session.query(CommitReport).filter(
            CommitReport.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        # TODO: component comparisons
        db_session.query(RepositoryFlag).filter_by(repository_id=repo.repoid).delete()
        db_session.commit()

        db_session.query(CommitError).filter(
            CommitError.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.query(CommitNotification).filter(
            CommitNotification.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.commit()

        # static analysis
        db_session.query(StaticAnalysisSuite).filter(
            StaticAnalysisSuite.commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        snapshot_ids = db_session.query(StaticAnalysisSingleFileSnapshot.id_).filter_by(
            repository_id=repo.repoid
        )
        db_session.query(StaticAnalysisSuiteFilepath).filter(
            StaticAnalysisSuiteFilepath.file_snapshot_id.in_(snapshot_ids)
        ).delete(synchronize_session=False)
        db_session.query(StaticAnalysisSingleFileSnapshot).filter_by(
            repository_id=repo.repoid
        ).delete()
        db_session.commit()

        # label analysis
        db_session.query(LabelAnalysisRequest).filter(
            LabelAnalysisRequest.base_commit_id.in_(commit_ids)
            | LabelAnalysisRequest.head_commit_id.in_(commit_ids)
        ).delete(synchronize_session=False)
        db_session.commit()

        deleted_commits = (
            db_session.query(Commit).filter_by(repoid=repo.repoid).delete()
        )
        delete_branches = (
            db_session.query(Branch).filter_by(repoid=repo.repoid).delete()
        )
        deleted_pulls = db_session.query(Pull).filter_by(repoid=repo.repoid).delete()
        repo.yaml = None
        return {
            "deleted_commits_count": deleted_commits,
            "delete_branches_count": delete_branches,
            "deleted_pulls_count": deleted_pulls,
            "deleted_archives": deleted_archives,
        }


FlushRepo = celery_app.register_task(FlushRepoTask())
flush_repo = celery_app.tasks[FlushRepo.name]
