import logging

from app import celery_app
from tasks.base import BaseCodecovTask
from helpers import archive
from services.repository import get_repo

log = logging.getLogger(__name__)


class FlushRepo(BaseCodecovTask):

    async def run_async(self, db_session, repoid, *args, **kwargs):
        log.info("in flush_repo tas  task_id: %s" % repoid)
        # delete archives
        repository = get_repo(db_session, repoid, commitid=None, use_integration=True)
        archive.delete_from_archive('v4/repos/{}/'.format(
            archive.get_archive_hash(repository)
        ))
        # delete database entries
        db_session.execute("DELETE from commits where repoid=%s;", repoid)
        db_session.execute("DELETE from branches where repoid=%s;", repoid)
        db_session.execute("DELETE from pulls where repoid=%s;", repoid)
        db_session.execute("""UPDATE repos
                         set cache=null, yaml=null, updatestamp=now()
                         where repoid=%s;""", repoid)

FlushRepo = celery_app.register_task(FlushRepo())
flush_repo = celery_app.tasks[FlushRepo.name]
