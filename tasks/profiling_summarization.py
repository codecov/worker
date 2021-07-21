import logging
from datetime import timedelta, datetime
from typing import Tuple, Sequence, Dict
import statistics
import json

from database.models.profiling import ProfilingCommit, ProfilingUpload
from shared.storage.exceptions import FileNotInStorageError
from tasks.base import BaseCodecovTask
from sqlalchemy.orm.session import Session
from services.archive import ArchiveService
from app import celery_app

log = logging.getLogger(__name__)


class ProfilingSummarizationTask(BaseCodecovTask):

    name = "app.tasks.profilingsummarizationtask"


RegisteredProfilingSummarizationTask = celery_app.register_task(
    ProfilingSummarizationTask()
)
profiling_summarization_task = celery_app.tasks[
    RegisteredProfilingSummarizationTask.name
]
