import logging
from itertools import islice
from typing import List

import sentry_sdk

from database.engine import Session
from database.models import (
    Commit,
    Upload,
    UploadError,
    UploadLevelTotals,
    uploadflagmembership,
)

log = logging.getLogger(__name__)


@sentry_sdk.trace
def delete_upload_by_ids(db_session: Session, upload_ids: List[int], commit: Commit):
    db_session.query(UploadError).filter(UploadError.upload_id.in_(upload_ids)).delete(
        synchronize_session=False
    )
    db_session.query(UploadLevelTotals).filter(
        UploadLevelTotals.upload_id.in_(upload_ids)
    ).delete(synchronize_session=False)
    db_session.query(uploadflagmembership).filter(
        uploadflagmembership.c.upload_id.in_(upload_ids)
    ).delete(synchronize_session=False)
    db_session.query(Upload).filter(Upload.id_.in_(upload_ids)).delete(
        synchronize_session=False
    )
    db_session.commit()
    log.info(
        "Deleted uploads",
        extra=dict(
            commit=commit.commitid,
            repo=commit.repoid,
            number_uploads=len(upload_ids),
            upload_ids=islice(upload_ids, 20),
        ),
    )
