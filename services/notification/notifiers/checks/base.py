import logging
from contextlib import nullcontext

from services.notification.notifiers.base import (
    AbstractBaseNotifier,
    Comparison,
    NotificationResult,
)
from typing import Dict
from services.urls import get_commit_url, get_compare_url, get_pull_url
from services.repository import get_repo_provider_service

log = logging.getLogger(__name__)


class ChecksNotifier(AbstractBaseNotifier):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._repository_service = None

    def is_enabled(self) -> bool:
        return True

    def store_results(self, comparison: Comparison, result: NotificationResult) -> bool:
        pass

    @property
    def name(self):
        return f"checks-{self.context}"

    def get_notifier_filters(self) -> dict:
        return dict(flags=self.notifier_yaml_settings.get("flags"),)

    def get_upgrade_message(self) -> str:
        return "Please activate this user to display a detailed status check"

    async def build_payload(self, comparison) -> Dict[str, str]:
        raise NotImplementedError()

    def get_status_external_name(self) -> str:
        status_piece = f"/{self.title}" if self.title != "default" else ""
        return f"codecov/{self.context}{status_piece}"

    async def notify(self, comparison: Comparison):
        if comparison.pull is None:
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="no_pull_request",
                data_sent=None,
                data_received=None,
            )
        if (
            comparison.enriched_pull is None
            or comparison.enriched_pull.provider_pull is None
        ):
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_not_in_provider",
                data_sent=None,
                data_received=None,
            )
        if comparison.pull.state != "open":
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_closed",
                data_sent=None,
                data_received=None,
            )

        _filters = self.get_notifier_filters()
        base_full_commit = comparison.base
        try:
            with comparison.head.report.filter(**_filters):
                with (
                    base_full_commit.report.filter(**_filters)
                    if comparison.has_base_report()
                    else nullcontext()
                ):
                    payload = await self.build_payload(comparison)
            if (
                comparison.pull
                and self.notifier_yaml_settings.get("base") in ("pr", "auto", None)
                and comparison.base.commit is not None
            ):
                payload["url"] = get_compare_url(
                    comparison.base.commit, comparison.head.commit
                )
            else:
                payload["url"] = get_commit_url(comparison.head.commit)
            return await self.send_notification(comparison, payload)
        except Exception as e:
            log.error(e)

    async def get_diff(self, comparison: Comparison):
        repository_service = self.repository_service
        head = comparison.head.commit
        base = comparison.base.commit
        if base is None:
            return None
        pull_diff = await repository_service.get_compare(
            base.commitid, head.commitid, with_commits=False
        )
        return pull_diff["diff"]

    def get_line_diff(self, file_diff):
        """
            This method traverses a git file diff and returns the lines (as line numbers) that where chnaged
            Note: For now it only looks for line additions on diff, we can quickly add functionality to handle
                  line deletions if needed

            Parameters:
                file_diff: file diff returned by repository.get_compare method.
                    structure:
                    {
                        "type": (str),
                        "path": (str),
                        "segments": [
                            {
                                "header": [
                                    base reference offset,
                                    number of lines in file-segment before changes applied,
                                    head reference offset,
                                    number of lines in file-segment after changes applied
                                ],
                                "lines": [ # line values for lines in the diff
                                    "+this is an added line",
                                    "-this is a removed line",
                                    "this line is unchanged in the diff",
                                    ...
                                ]
                            }
                        ]
                    }

        """
        segments = file_diff["segments"]
        if len(segments) <= 0:
            return None

        lines_diff = []
        for segment in segments:
            header = segment["header"]
            lines = segment["lines"]
            base_ln = int(header[0])
            head_ln = int(header[2])
            while not len(lines) == 0:
                line_value = lines.pop(0)
                if line_value and line_value[0] == "+":
                    lines_diff.append({"head_line": head_ln})
                    head_ln += 1
                elif line_value and line_value[0] == "-":
                    base_ln += 1
                else:
                    head_ln += 1
                    base_ln += 1
            file_diff["additions"] = lines_diff
        return file_diff

    def get_codecov_pr_link(self, comparison):
        return f"[View this Pull Request on Codecov]({get_pull_url(comparison.pull)}?src=pr&el=h1)"

    def get_lines_to_annotate(self, comparison, files_with_change):
        lines_diff = []
        for _file in files_with_change:
            if _file is None:
                continue
            head_file_report = comparison.head.report.get(_file["path"])
            for head_line in head_file_report.lines:
                line_addition = next(
                    (
                        line
                        for line in _file["additions"]
                        if head_line[0] == line["head_line"]
                    ),
                    None,
                )
                if line_addition and head_line[1].coverage == 0:
                    lines_diff.append(
                        {
                            "type": "new_line",
                            "line": head_line[0],
                            "coverage": head_line[1].coverage,
                            "path": _file["path"],
                        }
                    )
        line_headers = []
        previous_line = {}
        for index, line in enumerate(lines_diff):
            if index == 0:
                line_headers.append(line)
            elif line["line"] != previous_line["line"] + 1:
                line_headers[len(line_headers) - 1]["end_line"] = previous_line["line"]
                line_headers.append(line)
            if index == len(lines_diff) - 1:
                line_headers[len(line_headers) - 1]["end_line"] = line["line"]
            previous_line = line
        return line_headers

    def create_annotations(self, comparison, diff):
        files_with_change = [
            {"type": _diff["type"], "path": path, "segments": _diff["segments"]}
            for path, _diff in (diff["files"] if diff else {}).items()
            if _diff.get("totals")
        ]
        file_additions = [self.get_line_diff(_file,) for _file in files_with_change]
        lines_to_annotate = self.get_lines_to_annotate(comparison, file_additions)
        annotations = []
        for line in lines_to_annotate:
            annotation = {
                "path": line["path"],
                "start_line": line["line"],
                "end_line": line["end_line"],
                "annotation_level": "warning",
                "message": (
                    "Added lines #L{} - L{} were not covered by tests".format(
                        line["line"], line["end_line"]
                    )
                    if line["line"] != line["end_line"]
                    else "Added line #L{} was not covered by tests".format(line["line"])
                ),
            }
            annotations.append(annotation)
        return annotations

    @property
    def repository_service(self):
        if not self._repository_service:
            self._repository_service = get_repo_provider_service(self.repository)
        return self._repository_service

    async def send_notification(self, comparison: Comparison, payload):
        title = self.get_status_external_name()
        repository_service = self.repository_service
        head = comparison.head.commit
        head_report = comparison.head.report
        state = payload["state"]
        state = "success" if self.notifier_yaml_settings.get("informational") else state
        # We need to first create the check run, get that id and update the status
        check_id = await repository_service.create_check_run(
            check_name=title, head_sha=head.commitid
        )
        await repository_service.update_check_run(
            check_id, state, output=payload["output"]
        )
        return NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent=payload,
        )
