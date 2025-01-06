from typing import Any

from sqlalchemy.orm import Session

from database.models.reports import Upload
from services.ta_finishing import (
    DailyTotals,
    get_repo_flag_ids,
    modify_structures,
    save_daily_test_rollups,
    save_test_flag_bridges,
    save_test_instances,
    save_tests,
)
from ta_storage.base import TADriver


class PGDriver(TADriver):
    def __init__(self, db_session: Session, flaky_test_set: set):
        self.db_session = db_session
        self.flaky_test_set = flaky_test_set

    def write_testruns(
        self,
        repo_id: int,
        commit_id: str,
        branch: str,
        upload: Upload,
        framework: str | None,
        testruns: list[dict[str, Any]],
    ):
        tests_to_write: dict[str, dict[str, Any]] = {}
        test_instances_to_write: list[dict[str, Any]] = []
        daily_totals: dict[str, DailyTotals] = dict()
        test_flag_bridge_data: list[dict] = []

        repo_flag_ids = get_repo_flag_ids(self.db_session, repo_id, upload.flag_names)

        for testrun in testruns:
            modify_structures(
                tests_to_write,
                test_instances_to_write,
                test_flag_bridge_data,
                daily_totals,
                testrun,
                upload,
                repo_id,
                branch,
                commit_id,
                repo_flag_ids,
                self.flaky_test_set,
                framework,
            )

        if len(tests_to_write) > 0:
            print(tests_to_write)
            save_tests(self.db_session, tests_to_write)

        if len(test_flag_bridge_data) > 0:
            save_test_flag_bridges(self.db_session, test_flag_bridge_data)

        if len(daily_totals) > 0:
            save_daily_test_rollups(self.db_session, daily_totals)

        if len(test_instances_to_write) > 0:
            save_test_instances(self.db_session, test_instances_to_write)

        upload.state = "v2_persisted"
        self.db_session.commit()
