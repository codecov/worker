import logging

from sqlalchemy import null

from app import celery_app

# from database.models import ProfilingCommit
from tasks.base import BaseCodecovTask
from services.archive import ArchiveService
from sqlalchemy.orm.session import Session
import statistics


log = logging.getLogger(__name__)


class ProfilingSummarizationTask(BaseCodecovTask):

    name = "app.tasks.profilingsummarizationtask"

    async def run_async(
        self, db_session: Session, *, profiling_id: int, **kwargs,
    ):
        profiling = db_session.query(ProfilingCommit).filter_by(id=profiling_id).first()
        totalized_execution_counts: dict = self.get_totalized_execution_counts(
            profiling
        )  # fetch the data from storage
        summarized_results = self.summarize(
            totalized_execution_counts
        )  # take the data and turn into a result
        self.store_summarized_results(summarized_results)
        return {}

    def get_totalized_execution_counts(self, profiling: "ProfilingCommit"):
        pass

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
        for file_dict in totalized_execution_counts["files"]:
            filename = file_dict["filename"]
            file_count_so_far = 0
            for l_number, ex_count in file_dict["ln_ex_ct"]:
                file_count_so_far += ex_count
            line_executions_map[filename] = file_count_so_far
        k = statistics.quantiles(line_executions_map.values(), n=100)
        print(line_executions_map)
        stdev = statistics.stdev(line_executions_map.values())
        mean = statistics.mean(line_executions_map.values())
        print(f"{mean=} {stdev=} {mean + stdev=}")
        return {
            "file_groups": {
                "sum_of_executions": {
                    "top_10_percent": [
                        f for (f, v) in line_executions_map.items() if v >= k[89]
                    ],
                    "above_1_stdev": [
                        f for (f, v) in line_executions_map.items() if v >= mean + stdev
                    ],
                }
            }
        }

    def store_summarized_results(self, summarized_results):
        pass
