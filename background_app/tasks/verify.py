import logging

from app import celery_app
from tasks.base import BaseCodecovTask
from torngit import get

log = logging.getLogger(__name__)


class VerifyBot(BaseCodecovTask):

    async def run(self, db_session, repoid, *args, **kwargs):
        repository = get
        try:
            can_view, can_edit = await repository.get_authenticated()
            assert can_edit

            try:
                await repository.get_repository()
                return True
            except Exception:
                # user does not have access to repo
                log('error', 'Authorization access to project')

        except AssertionError:
            # we cannot edit this project
            log('error', 'Write permission not permitted')

        except Exception:
            # user token no longer valid
            log('error', 'User token is invalid')


verify_bot = celery_app.tasks[VerifyBot.name]
