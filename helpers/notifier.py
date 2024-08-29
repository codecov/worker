import logging
from dataclasses import dataclass
from enum import Enum

from shared.torngit.base import TorngitBaseAdapter
from shared.torngit.exceptions import TorngitClientError

from database.models import Commit
from services.repository import (
    EnrichedPull,
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.yaml import UserYaml

log = logging.getLogger(__name__)


class NotifierResult(Enum):
    COMMENT_POSTED = "comment_posted"
    TORNGIT_ERROR = "torngit_error"
    NO_PULL = "no_pull"


@dataclass
class BaseNotifier:
    commit: Commit
    commit_yaml: UserYaml | None
    _pull: EnrichedPull | None = None
    _repo_service: TorngitBaseAdapter | None = None

    async def get_pull(self):
        repo_service = self.get_repo_service()

        if self._pull is None:
            self._pull = await fetch_and_update_pull_request_information_from_commit(
                repo_service, self.commit, self.commit_yaml
            )

        return self._pull

    def get_repo_service(self):
        if self._repo_service is None:
            self._repo_service = get_repo_provider_service(self.commit.repository)

        return self._repo_service

    async def send_to_provider(self, pull, message):
        repo_service = self.get_repo_service()
        assert repo_service

        pullid = pull.database_pull.pullid
        try:
            comment_id = pull.database_pull.commentid
            if comment_id:
                await repo_service.edit_comment(pullid, comment_id, message)
            else:
                res = await repo_service.post_comment(pullid, message)
                pull.database_pull.commentid = res["id"]
            return True
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    pullid=pullid,
                ),
            )
            return False

    def build_message(self) -> str:
        raise NotImplementedError

    async def notify(
        self,
    ) -> NotifierResult:
        pull = await self.get_pull()
        if pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                ),
            )
            return NotifierResult.NO_PULL

        message = self.build_message()

        sent_to_provider = await self.send_to_provider(pull, message)
        if sent_to_provider == False:
            return NotifierResult.TORNGIT_ERROR

        return NotifierResult.COMMENT_POSTED
