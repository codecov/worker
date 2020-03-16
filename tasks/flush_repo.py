import logging

from app import celery_app
from database.models import Repository
from tasks.base import BaseCodecovTask
from services.archive import ArchiveService

log = logging.getLogger(__name__)


class FlushRepo(BaseCodecovTask):
    async def run_async(self, db_session, repoid, *args, **kwargs):
        log.info("in flush_repo tas  task_id: %s" % repoid)
        # delete archives
        repo = db_session.query(Repository).filter_by(repoid=repoid)
        archive_service = ArchiveService(repo)
        archive_service.delete_repo_files()
        # delete database entries
        db_session.execute("DELETE from commits where repoid=%s;", repoid)
        db_session.execute("DELETE from branches where repoid=%s;", repoid)
        db_session.execute("DELETE from pulls where repoid=%s;", repoid)
        db_session.execute(
            """UPDATE repos
                         set cache=null, yaml=null, updatestamp=now()
                         where repoid=%s;""",
            repoid,
        )


FlushRepo = celery_app.register_task(FlushRepo())
flush_repo = celery_app.tasks[FlushRepo.name]
