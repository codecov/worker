import logging

from tasks.base import BaseCodecovTask
from helpers import archive
from app.helpers import get_archive_hash
from services.repository import get_repo

log = logging.getLogger(__name__)


class FlushRepo(BaseCodecovTask):

    async def run_async(self, db_session, repoid, *args, **kwargs):
        # delete archives
        repository = get_repo(db_session, repoid, commitid=None, use_integration=True)
        archive.delete_from_archive('v4/repos/{}/'.format(
            get_archive_hash(repository)
        ))
        # delete database entries
        db_session.execute("DELETE from commits where repoid=%s;", repoid)
        db_session.execute("DELETE from branches where repoid=%s;", repoid)
        db_session.execute("DELETE from pulls where repoid=%s;", repoid)
        db_session.execute("""UPDATE repos
                         set cache=null, yaml=null, updatestamp=now()
                         where repoid=%s;""", repoid)
