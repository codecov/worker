import logging
from dataclasses import dataclass
from enum import Enum

from shared.rate_limits.exceptions import EntityRateLimitedException
from shared.torngit.exceptions import TorngitClientError

from database.models import Commit
from services.repository import (
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
    commit_yaml: UserYaml

    async def get_pull(self):
        self.pull = await fetch_and_update_pull_request_information_from_commit(
            self.repo_service, self.commit, self.commit_yaml
        )

    async def send_to_provider(self, message):
        pullid = self.pull.database_pull.pullid
        try:
            comment_id = self.pull.database_pull.commentid
            if comment_id:
                await self.repo_service.edit_comment(pullid, comment_id, message)
            else:
                res = await self.repo_service.post_comment(pullid, message)
                self.pull.database_pull.commentid = res["id"]
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
        try:
            self.repo_service = get_repo_provider_service(self.commit.repository)
        except EntityRateLimitedException as e:
            log.warning(
                f"Entity {e.entity_name} rate limited trying to notify. Please try again later"
            )

        await self.get_pull()
        if self.pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                ),
            )
            return NotifierResult.NO_PULL

        message = self.build_message()

        sent_to_provider = await self.send_to_provider(message)
        if sent_to_provider == False:
            return NotifierResult.TORNGIT_ERROR

        return NotifierResult.COMMENT_POSTED
