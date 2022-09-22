import logging

from shared.staticanalysis import StaticAnalysisSingleFileSnapshotState

from app import celery_app
from database.models.staticanalysis import (
    StaticAnalysisSingleFileSnapshot,
    StaticAnalysisSuite,
    StaticAnalysisSuiteFilepath,
)
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class StaticAnalysisSuiteCheckTask(BaseCodecovTask):
    # TODO: Move to shared
    name = "app.tasks.staticanalysis.check_suite"

    async def run_async(
        self,
        db_session,
        *,
        suite_id,
        **kwargs,
    ):
        suite = db_session.query(StaticAnalysisSuite).filter_by(id_=suite_id).first()
        if suite is None:
            log.warning("Checking Static Analysis that does not exist yet")
            return {"successful": False, "changed_count": None}
        log.info("Checking static analysis suite", extra=dict(suite_id=suite_id))
        query = (
            db_session.query(StaticAnalysisSingleFileSnapshot)
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

        # purposefully iteration when an update would suffice,
        # because we actually want to validate different stuff
        changed_count = 0
        for elem in query:
            elem.state_id = StaticAnalysisSingleFileSnapshotState.VALID.db_id
            changed_count += 1
        db_session.commit()
        return {"successful": True, "changed_count": changed_count}


RegisteredStaticAnalysisSuiteCheckTask = celery_app.register_task(
    StaticAnalysisSuiteCheckTask()
)
static_analysis_suite_check_task = celery_app.tasks[
    RegisteredStaticAnalysisSuiteCheckTask.name
]
