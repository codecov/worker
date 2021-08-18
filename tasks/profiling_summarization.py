import json
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, Sequence, Tuple

from shared.storage.exceptions import FileNotInStorageError
from sqlalchemy.orm.session import Session

from app import celery_app
from database.models.profiling import ProfilingCommit, ProfilingUpload
from services.archive import ArchiveService
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class ProfilingSummarizationTask(BaseCodecovTask):

    name = "app.tasks.profilingsummarizationtask"

    async def run_async(
        self, db_session: Session, *, profiling_id: int, **kwargs,
    ):
        profiling = db_session.query(ProfilingCommit).filter_by(id=profiling_id).first()
        try:
            joined_execution_counts = json.loads(
                ArchiveService(profiling.repository).read_file(
                    profiling.joined_location
                )
            )
        except FileNotInStorageError:
            return {"successful": False}
        summarized_results = self.summarize(joined_execution_counts)
        location = self.store_results(profiling, summarized_results)
        return {"successful": True, "location": location}

    def summarize(self, totalized_execution_counts: dict) -> dict:
        """
            {
                "metadata": {"version": "v7"},
                "files": [
                    {"filename": "abc.py", "ln_ex_ct": [[1, 1000], [5, 6], [6, 0]]},
                    {"filename": "bcd.py", "ln_ex_ct": [[1, 333], [5, 3333], [6, 333]]},
                    {"filename": "cde.py", "ln_ex_ct": [[1, 10], [5, 6], [6, 0]]},
                    {"filename": "def.py", "ln_ex_ct": [[1, 10], [5, 6], [6, 0]]},
                    ...
                    {"filename": "stu.py", "ln_ex_ct": [[1, 10], [5, 6], [6, 0]]},
                    {"filename": "tuv.py", "ln_ex_ct": [[1, 10], [5, 6], [6, 0]]},
                    {"filename": "uvx.py", "ln_ex_ct": [[1, 10], [5, 6], [6, 0]]},
                ],
            }

        """
        line_executions_map = {}
        max_executions_map = {}
        avg_executions_map = {}
        for file_dict in totalized_execution_counts["files"]:
            filename = file_dict["filename"]
            file_count_so_far = 0
            max_lines_so_far = 0
            present_lines = 0
            for l_number, ex_count in file_dict["ln_ex_ct"]:
                present_lines += 1
                file_count_so_far += ex_count
                max_lines_so_far = max(max_lines_so_far, ex_count)
            line_executions_map[filename] = file_count_so_far
            max_executions_map[filename] = max_lines_so_far
            avg_executions_map[filename] = file_count_so_far / present_lines
        return {
            "version": "v1",
            "general": {"total_profiled_files": len(line_executions_map.keys())},
            "file_groups": {
                "sum_of_executions": self._generate_stats_from_mapping(
                    line_executions_map
                ),
                "max_number_of_executions": self._generate_stats_from_mapping(
                    max_executions_map
                ),
                "avg_number_of_executions": self._generate_stats_from_mapping(
                    avg_executions_map
                ),
            },
        }

    def _generate_stats_from_mapping(self, data):
        k = statistics.quantiles(data.values(), n=100)
        stdev = statistics.stdev(data.values())
        mean = statistics.mean(data.values())
        return {
            "top_10_percent": [f for (f, v) in data.items() if v >= k[89]],
            "above_1_stdev": [f for (f, v) in data.items() if v >= mean + stdev],
        }

    def store_results(self, profiling: ProfilingCommit, summarized_results):
        archive_service = ArchiveService(profiling.repository)
        location = archive_service.write_profiling_summary_result(
            profiling.version_identifier, json.dumps(summarized_results)
        )
        log.info("Summarized profiling data", extra=dict(location=location))
        profiling.summarized_location = location
        return location


RegisteredProfilingSummarizationTask = celery_app.register_task(
    ProfilingSummarizationTask()
)
profiling_summarization_task = celery_app.tasks[
    RegisteredProfilingSummarizationTask.name
]
