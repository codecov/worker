import logging

from sqlalchemy import null

from app import celery_app
from database.models import Repository, Commit, Branch, Pull
from tasks.base import BaseCodecovTask
from services.archive import ArchiveService

log = logging.getLogger(__name__)


class FlushRepoTask(BaseCodecovTask):

    name = "app.tasks.flush_repo.FlushRepo"

    async def run_async(self, db_session, *, repoid: int, **kwargs):
        log.info("Deleting repo contents", extra=dict(repoid=repoid))
        repo = db_session.query(Repository).filter_by(repoid=repoid).first()
        archive_service = ArchiveService(repo)
        deleted_archives = archive_service.delete_repo_files()
        deleted_commits = (
            db_session.query(Commit).filter_by(repoid=repo.repoid).delete()
        )
        delete_branches = (
            db_session.query(Branch).filter_by(repoid=repo.repoid).delete()
        )
        deleted_pulls = db_session.query(Pull).filter_by(repoid=repo.repoid).delete()
        repo.yaml = None
        # Be aware of SQL NULL vs JSON 'null'. This is the first one
        repo.cache_do_not_use = null()
        return {
            "deleted_commits_count": deleted_commits,
            "delete_branches_count": delete_branches,
            "deleted_pulls_count": deleted_pulls,
            "deleted_archives": deleted_archives,
        }


FlushRepo = celery_app.register_task(FlushRepoTask())
flush_repo = celery_app.tasks[FlushRepo.name]
