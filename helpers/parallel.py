from __future__ import annotations

from enum import Enum

import sentry_sdk
from shared.metrics import Counter

from rollouts import PARALLEL_UPLOAD_PROCESSING_BY_REPO

PARALLEL_TASK_RUNS = Counter(
    "worker_parallel_task_runs",
    "Number of tasks run using different parallel processing configurations.",
    ["task", "parallel_mode"],
)

"""
This encapsulates Parallel Upload Processing logic

Upload Processing can run in essentially 4 modes:
- Completely serial processing
- Serial processing, but running "experiment" code (`EXPERIMENT_SERIAL`):
  - In this mode, the final (`is_final`) `UploadProcessor` task saves a copy
    of the final report for later verification.
- Parallel processing, but running "experiment" code (`EXPERIMENT_PARALLEL`):
  - In this mode, another parallel set of `UploadProcessor` tasks runs *after*
    the main set up tasks.
  - These tasks are not persisting any of their results in the database,
    instead the final `UploadFinisher` task will launch the `ParallelVerification` task.
- Fully parallel processing (`PARALLEL`):
  - In this mode, the final `UploadFinisher` task is responsible for merging
    the final report and persisting it.

An example Task chain might look like this, in "experiment" mode:
- Upload
  - UploadProcessor
    - UploadProcessor
      - UploadProcessor (`EXPERIMENT_SERIAL` (the final one))
        - UploadFinisher
          - UploadProcessor (`EXPERIMENT_PARALLEL`)
          - UploadProcessor (`EXPERIMENT_PARALLEL`)
          - UploadProcessor (`EXPERIMENT_PARALLEL`)
            - UploadFinisher (`EXPERIMENT_PARALLEL`)
              - ParallelVerification


The `PARALLEL` mode looks like this:
- Upload
  - UploadProcessor (`PARALLEL`)
  - UploadProcessor (`PARALLEL`)
  - UploadProcessor (`PARALLEL`)
    - UploadFinisher (`PARALLEL`)
"""


class ParallelFeature(Enum):
    SERIAL = "serial"
    EXPERIMENT = "experiment"
    PARALLEL = "parallel"

    @classmethod
    def load(cls, repoid: int) -> ParallelFeature:
        feature = PARALLEL_UPLOAD_PROCESSING_BY_REPO.check_value(
            identifier=repoid, default="serial"
        )

        if feature == "experiment" or feature is True:
            return ParallelFeature.EXPERIMENT
        if feature == "parallel":
            return ParallelFeature.PARALLEL
        return ParallelFeature.SERIAL


class ParallelProcessing(Enum):
    SERIAL = "serial"
    EXPERIMENT_SERIAL = "experiment-serial"
    EXPERIMENT_PARALLEL = "experiment-parallel"
    PARALLEL = "parallel"

    @property
    def is_parallel(self) -> bool:
        return (
            self is ParallelProcessing.EXPERIMENT_PARALLEL
            or self is ParallelProcessing.PARALLEL
        )

    @classmethod
    def from_task_args(
        cls,
        in_parallel: bool = False,
        is_final: bool = False,
        run_fully_parallel: bool = False,
        **kwargs,
    ) -> ParallelProcessing:
        if run_fully_parallel:
            return ParallelProcessing.PARALLEL
        if in_parallel:
            return ParallelProcessing.EXPERIMENT_PARALLEL
        if is_final:
            return ParallelProcessing.EXPERIMENT_SERIAL
        return ParallelProcessing.SERIAL

    def emit_metrics(self, task: str):
        sentry_sdk.set_tag("parallel_mode", self.value)
        PARALLEL_TASK_RUNS.labels(task=task, parallel_mode=self.value).inc()
