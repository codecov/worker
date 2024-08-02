import json
import logging
import re
from dataclasses import dataclass
from functools import cached_property
from typing import Dict, List, Optional

from openai import AsyncOpenAI
from shared.config import get_config
from shared.rate_limits.exceptions import EntityRateLimitedException
from shared.storage.exceptions import FileNotInStorageError
from shared.torngit.base import TokenType, TorngitBaseAdapter

from database.models.core import Repository
from helpers.metrics import metrics
from services.archive import ArchiveService
from services.repository import get_repo_provider_service

log = logging.getLogger(__name__)

FILE_REGEX = re.compile(r"diff --git a/(.+) b/(.+)")


def build_prompt(diff_text: str) -> str:
    return f"""
        Your purpose is to act as a highly experienced software engineer and provide a thorough
        review of code changes and suggest improvements.  Do not comment on minor style issues,
        missing comments or documentation.  Identify and resolve significant concerns to improve
        overall code quality.

        You will receive a Git diff where each line has been prefixed with a unique identifer in
        square brackets.  When referencing lines in this diff use that identifier.

        Format your output as JSON such that there is 1 top-level comment that summarizes your review
        and multiple additional comments addressing specific lines in the code with the changes you
        deem appropriate.

        The output should have this JSON form:

        {{
            "body": "This is the summary comment",
            "comments": [
                {{
                    "line_id": 123,
                    "body": "This is a comment about the code with line ID 123",
                }}
            ]
        }}

        Limit the number of comments to 10 at most.

        Here is the Git diff on which you should base your review:

        {diff_text}
    """


async def fetch_openai_completion(prompt: str):
    client = AsyncOpenAI(api_key=get_config("services", "openai", "api_key"))
    completion = await client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        model="gpt-4",
    )

    output = completion.choices[0].message.content
    return output


@dataclass(frozen=True)
class LineInfo:
    file_path: str
    position: int


class Diff:
    def __init__(self, diff):
        self._diff = diff
        self._index = {}
        self._build_index()

    @cached_property
    def preprocessed(self) -> str:
        """
        This returns the full diff but with each line prefixed by:
        [line_id] (where line_id is just a unique integer)
        """
        return "\n".join(
            [f"[{i+1}] {line}" for i, line in enumerate(self._diff.split("\n"))]
        )

    def line_info(self, line_id: int) -> LineInfo:
        return self._index[line_id]

    def _build_index(self):
        file_path = None
        position = None

        for idx, line in enumerate(self._diff.split("\n")):
            line_id = idx + 1
            match = FILE_REGEX.match(line)
            if match:
                # start of a new file, extract the name and reset the position
                file_path = match.groups()[-1]
                position = None
            elif line.startswith("@@"):
                # start of new hunk
                if position is None:
                    # 1st hunk of file, start tracking position
                    position = 0
                else:
                    # new hunk same file, just ignore but keep tracking position
                    pass
            elif position is not None:
                # code line, increment position and keep track of it in the index
                position += 1
                self._index[line_id] = LineInfo(file_path=file_path, position=position)


@dataclass
class Comment:
    body: str
    comment_id: Optional[int] = None


@dataclass
class ReviewComments:
    # top-level comment
    body: str

    # line-based code comments
    comments: Dict[LineInfo, Comment]


class PullWrapper:
    def __init__(self, torngit: TorngitBaseAdapter, pullid: int):
        self.torngit = torngit
        self.pullid = pullid
        self._head_sha = None

    @property
    def token(self):
        return self.torngit.get_token_by_type_if_none(None, TokenType.read)

    async def fetch_diff(self) -> str:
        async with self.torngit.get_client() as client:
            diff = await self.torngit.api(
                client,
                "get",
                f"/repos/{self.torngit.slug}/pulls/{self.pullid}",
                token=self.token,
                headers={"Accept": "application/vnd.github.v3.diff"},
            )
        return diff

    async def fetch_head_sha(self) -> str:
        if self._head_sha is not None:
            return self._head_sha

        async with self.torngit.get_client() as client:
            res = await self.torngit.api(
                client,
                "get",
                f"/repos/{self.torngit.slug}/pulls/{self.pullid}",
                token=self.token,
            )
        self._head_sha = res["head"]["sha"]
        return self._head_sha

    async def fetch_review_comments(self):
        async with self.torngit.get_client() as client:
            page = 1
            while True:
                res = await self.torngit.api(
                    client,
                    "get",
                    f"/repos/{self.torngit.slug}/pulls/{self.pullid}/comments?per_page=100&page={page}",
                    token=self.token,
                )
                if len(res) == 0:
                    break
                for item in res:
                    yield item
                page += 1

    async def create_review(self, commit_sha: str, review_comments: ReviewComments):
        body = dict(
            commit_id=commit_sha,
            body=review_comments.body,
            event="COMMENT",
            comments=[
                {
                    "path": line_info.file_path,
                    "position": line_info.position,
                    "body": comment.body,
                }
                for line_info, comment in review_comments.comments.items()
            ],
        )
        log.info(
            "Creating AI PR review",
            extra=body,
        )

        async with self.torngit.get_client() as client:
            res = await self.torngit.api(
                client,
                "post",
                f"/repos/{self.torngit.slug}/pulls/{self.pullid}/reviews",
                token=self.token,
                body=body,
            )
        return res

    async def update_comment(self, comment: Comment):
        log.info(
            "Updating comment",
            extra=dict(
                comment_id=comment.comment_id,
                body=comment.body,
            ),
        )
        async with self.torngit.get_client() as client:
            await self.torngit.api(
                client,
                "patch",
                f"/repos/{self.torngit.slug}/pulls/comments/{comment.comment_id}",
                token=self.token,
                body=dict(body=comment.body),
            )


class Review:
    def __init__(
        self, pull_wrapper: PullWrapper, review_ids: Optional[List[int]] = None
    ):
        self.pull_wrapper = pull_wrapper
        self.review_ids = review_ids or []
        self.diff = None

    async def perform(self) -> Optional[int]:
        raw_diff = await self.pull_wrapper.fetch_diff()
        self.diff = Diff(raw_diff)

        prompt = build_prompt(self.diff.preprocessed)
        log.debug(
            "OpenAI prompt",
            extra=dict(
                prompt=prompt,
            ),
        )

        res = await fetch_openai_completion(prompt)
        log.debug(
            "OpenAI response",
            extra=dict(
                res=res,
            ),
        )

        try:
            data = json.loads(res)
        except json.decoder.JSONDecodeError:
            metrics.incr("ai_pr_review.non_json_completion")
            log.error(
                "OpenAI completion was expected to be JSON but wasn't",
                extra=dict(res=res),
                exc_info=True,
            )
            return

        try:
            review_comments = ReviewComments(
                body=data["body"],
                comments={
                    self.diff.line_info(comment["line_id"]): Comment(
                        body=comment["body"]
                    )
                    for comment in data["comments"]
                },
            )
        except KeyError:
            metrics.incr("ai_pr_review.malformed_completion")
            log.error(
                "OpenAI completion JSON was not formed as expected",
                extra=dict(data=data),
                exc_info=True,
            )
            return

        if len(self.review_ids) > 0:
            comments_to_update = []
            async for comment in self.pull_wrapper.fetch_review_comments():
                if comment["pull_request_review_id"] not in self.review_ids:
                    continue

                line_info = LineInfo(
                    file_path=comment["path"],
                    position=comment["position"],
                )
                if line_info in review_comments.comments:
                    # we have an existing comment on this line that we'll need
                    # to update instead of create
                    line_comment = review_comments.comments[line_info]

                    # we'll update this existing comment
                    line_comment.comment_id = comment["id"]
                    comments_to_update.append(line_comment)

                    # remove it from the current review comments since those will
                    # be posted as new comments
                    del review_comments.comments[line_info]

            for comment in comments_to_update:
                await self.pull_wrapper.update_comment(comment)

        if len(review_comments.comments) > 0:
            head_commit_sha = await self.pull_wrapper.fetch_head_sha()
            if len(self.review_ids) > 0:
                # we already made a top-level comment w/ summary of suggestions,
                # this is more of a placeholder since we're obligated to pass a top-level
                # comment when creating a new review
                review_comments.body = (
                    f"CodecovAI submitted a new review for {head_commit_sha}"
                )
            res = await self.pull_wrapper.create_review(
                head_commit_sha, review_comments
            )
            return res["id"], head_commit_sha


async def perform_review(repository: Repository, pullid: int):
    try:
        repository_service = get_repo_provider_service(repository)
    except EntityRateLimitedException as e:
        log.warning(
            f"Entity {e.entity_name} rate limited on AI PR review. Please try again later"
        )
    pull_wrapper = PullWrapper(repository_service, pullid)

    archive = ArchiveService(repository)
    archive_path = f"ai_pr_review/{archive.storage_hash}/pull_{pullid}.json"

    archive_data = None
    try:
        archive_data = archive.read_file(archive_path)
        archive_data = json.loads(archive_data)
    except FileNotInStorageError:
        pass

    commit_sha = None
    review_ids = []
    if archive_data is not None:
        commit_sha = archive_data.get("commit_sha")
        review_ids = archive_data.get("review_ids", [])

    head_sha = await pull_wrapper.fetch_head_sha()
    if head_sha == commit_sha:
        log.info(
            "Review already performed on SHA",
            extra=dict(sha=head_sha),
        )
        return

    review = Review(pull_wrapper, review_ids=review_ids)
    res = await review.perform()
    if res is not None:
        # we created a new review
        review_id, commit_sha = res
        review_ids.append(review_id)

    archive.write_file(
        archive_path,
        json.dumps(
            {
                "commit_sha": commit_sha,
                "review_ids": review_ids,
            }
        ),
    )
