import logging
from typing import Optional

from shared.celery_config import static_analysis_task_name
from shared.staticanalysis import StaticAnalysisSingleFileSnapshotState
from shared.storage.exceptions import FileNotInStorageError

from app import celery_app
from database.models.staticanalysis import (
    StaticAnalysisSingleFileSnapshot,
    StaticAnalysisSuite,
    StaticAnalysisSuiteFilepath,
)
from helpers.telemetry import log_simple_metric
from services.archive import ArchiveService
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StaticAnalysisSuiteCheckTask(BaseCodecovTask, name=static_analysis_task_name):
    def run_impl(
        self,
        db_session,
        *,
        suite_id,
        **kwargs,
    ):
        suite: Optional[StaticAnalysisSuite] = (
            db_session.query(StaticAnalysisSuite).filter_by(id_=suite_id).first()
        )
        if suite is None:
            log.warning("Checking Static Analysis that does not exist yet")
            return {"successful": False, "changed_count": None}
        log.info("Checking static analysis suite", extra=dict(suite_id=suite_id))
        query = (
            db_session.query(
                StaticAnalysisSingleFileSnapshot,
                StaticAnalysisSingleFileSnapshot.content_location,
            )
            .join(
                StaticAnalysisSuiteFilepath,
                StaticAnalysisSuiteFilepath.file_snapshot_id
                == StaticAnalysisSingleFileSnapshot.id_,
            )
            .filter(
                StaticAnalysisSuiteFilepath.analysis_suite_id == suite_id,
                StaticAnalysisSingleFileSnapshot.state_id
                == StaticAnalysisSingleFileSnapshotState.CREATED.db_id,
            )
        )
        archive_service = ArchiveService(suite.commit.repository)
        # purposefully iteration when an update would suffice,
        # because we actually want to validate different stuff
        changed_count = 0
        for elem, content_location in query:
            try:
                _ = archive_service.read_file(content_location)
                elem.state_id = StaticAnalysisSingleFileSnapshotState.VALID.db_id
                changed_count += 1
            except FileNotInStorageError:
                log.warning(
                    "File not found to be analyzed",
                    extra=dict(filepath_id=elem.id, suite_id=suite_id),
                )

        db_session.commit()
        log_simple_metric("static_analysis.data_sent_for_commit", float(True))
        log_simple_metric("static_analysis.files_changed", changed_count)
        return {"successful": True, "changed_count": changed_count}


RegisteredStaticAnalysisSuiteCheckTask = celery_app.register_task(
    StaticAnalysisSuiteCheckTask()
)
static_analysis_suite_check_task = celery_app.tasks[
    RegisteredStaticAnalysisSuiteCheckTask.name
]
