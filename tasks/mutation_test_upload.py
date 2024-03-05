from app import celery_app
from database.models.core import Repository
from database.models.reports import Upload
from services.archive import ArchiveService
from tasks.base import BaseCodecovTask


# TODO: Move task name to shared
class MutationTestUploadTask(BaseCodecovTask, name="app.tasks.mutation_test.upload"):
    def run_impl(
        self,
        db_session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
        **kwargs,
    ):
        """
        Task to process mutation test uploads.
        Currently does nothing.

        For testing purposes I'm making it read the file from storage and run it through a validator function.
        """
        repository = db_session.query(Repository).filter_by(repoid=repoid).first()
        archive_service = ArchiveService(repository)
        try:
            archive_url = kwargs["upload_path"]
            raw_file = archive_service.read_file(archive_url)
        except Exception:
            raise
        return raw_file.decode()


RegisteredMutationTestUploadTask = celery_app.register_task(MutationTestUploadTask())
mutation_test_upload_task = celery_app.tasks[RegisteredMutationTestUploadTask.name]
