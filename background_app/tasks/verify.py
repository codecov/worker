import logging

from app import celery_app
from tasks.base import BaseCodecovTask
from services.repository import get_repo

log = logging.getLogger(__name__)


class VerifyBot(BaseCodecovTask):

    async def run_async(self, db_session, repoid, *args, **kwargs):
        repository = get_repo(db_session, repoid, commitid=None, use_integration=True)
        try:
            can_view, can_edit = await repository.get_authenticated()
            assert can_edit
        except AssertionError:
            # we cannot edit this project
            log.error('Write permission not permitted', exc_info=True)

        except Exception:
            # user token no longer valid
            log.error('User token is invalid', exc_info=True)
        try:
            await repository.get_repository()
            return True
        except Exception:
            # user does not have access to repo
            log.error('Authorization access to project', exc_info=True)


VerifyBot = celery_app.register_task(VerifyBot())
verify_bot = celery_app.tasks[VerifyBot.name]
