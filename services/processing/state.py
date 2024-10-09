"""
This abstracts the "processing state" for a commit.

It takes care that each upload for a specific commit is going through the following
states:

- "processing": when an upload was received and is being parsed/processed.
- "processed": the upload has been processed and an "intermediate report" has been stored,
  the upload is now waiting to be merged into the "master report".
- "merged": the upload was fully merged into the "master report".

The logic in this file also makes sure that processing and merging happens in an "optimal" way
meaning that:

- "postprocessing", which means triggering notifications and other followup work
  only happens once for a commit.
- merging should happen in batches, as that involves loading a bunch of "intermediate report"s
  into memory, which should be bounded.
- (ideally in the future) an upload that has been processed into an "intermediate report"
  should be merged directly into the "master report" without doing a storage roundtrip for that
  "intermediate report".
"""

from dataclasses import dataclass

from services.redis import get_redis_connection

MERGE_BATCH_SIZE = 5


@dataclass
class UploadNumbers:
    processing: int
    """
    The number of uploads currently being processed.
    """

    processed: int
    """
    The number of uploads that have been processed,
    and are waiting on being merged into the "master report".
    """


def should_perform_merge(uploads: UploadNumbers) -> bool:
    """
    Determines whether a merge should be performed.

    This is the case when no more uploads are expected,
    or we reached the desired batch size for merging.
    """
    return uploads.processing == 0 or uploads.processed >= MERGE_BATCH_SIZE


def should_trigger_postprocessing(uploads: UploadNumbers) -> bool:
    """
    Determines whether post-processing steps, such as notifications, etc,
    should be performed.

    This is the case when no more uploads are expected,
    and all the processed uploads have been merged into the "master report".
    """
    return uploads.processing == 0 and uploads.processed == 0


class ProcessingState:
    def __init__(self, repoid: int, commitsha: str) -> None:
        self._redis = get_redis_connection()
        self.repoid = repoid
        self.commitsha = commitsha

    def get_upload_numbers(self):
        processing = self._redis.scard(self._redis_key("processing"))
        processed = self._redis.scard(self._redis_key("processed"))
        return UploadNumbers(processing, processed)

    def mark_uploads_as_processing(self, upload_ids: list[int]):
        self._redis.sadd(self._redis_key("processing"), *upload_ids)

    def clear_in_progress_uploads(self, upload_ids: list[int]):
        self._redis.srem(self._redis_key("processing"), *upload_ids)

    def mark_upload_as_processed(self, upload_id: int):
        res = self._redis.smove(
            self._redis_key("processing"), self._redis_key("processed"), upload_id
        )
        if not res:
            # this can happen when `upload_id` was never in the source set,
            # which probably is the case during initial deployment as
            # the code adding this to the initial set was not deployed yet
            # TODO: make sure to remove this code after a grace period
            self._redis.sadd(self._redis_key("processed"), upload_id)

    def mark_uploads_as_merged(self, upload_ids: list[int]):
        self._redis.srem(self._redis_key("processed"), *upload_ids)

    def get_uploads_for_merging(self) -> set[int]:
        return set(
            int(id)
            for id in self._redis.srandmember(
                self._redis_key("processed"), MERGE_BATCH_SIZE
            )
        )

    def _redis_key(self, state: str) -> str:
        return f"upload-processing-state/{self.repoid}/{self.commitsha}/{state}"
