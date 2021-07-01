import logging
from contextlib import nullcontext
from services.yaml.reader import get_paths_from_flags
from shared.torngit.exceptions import TorngitClientError, TorngitError
from services.notification.notifiers.base import (
    Comparison,
    NotificationResult,
)
from services.notification.notifiers.status.base import StatusNotifier
from typing import Dict
from services.urls import (
    get_commit_url,
    get_compare_url,
    get_pull_url,
    get_org_account_url,
    append_tracking_params_to_urls,
)
from services.repository import get_repo_provider_service
from helpers.metrics import metrics


log = logging.getLogger(__name__)


class ChecksNotifier(StatusNotifier):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._repository_service = None

    ANNOTATIONS_PER_REQUEST = 50

    def is_enabled(self) -> bool:
        return True

    def store_results(self, comparison: Comparison, result: NotificationResult) -> bool:
        pass

    @property
    def name(self):
        return f"checks-{self.context}"

    def get_notifier_filters(self) -> dict:
        flag_list = self.notifier_yaml_settings.get("flags") or []
        return dict(
            path_patterns=set(
                get_paths_from_flags(self.current_yaml, flag_list)
                + (self.notifier_yaml_settings.get("paths") or [])
            ),
            flags=flag_list,
        )

    def get_upgrade_message(self, comparison: Comparison) -> str:
        db_pull = comparison.enriched_pull.database_pull
        links = {
            "org_account": get_org_account_url(db_pull),
        }
        author_username = comparison.enriched_pull.provider_pull["author"].get(
            "username"
        )
        return "\n".join(
            [
                f"The author of this PR, {author_username}, is not an activated member of this organization on Codecov.",
                f"Please [activate this user on Codecov]({links['org_account']}/users) to display a detailed status check.",
                f"Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
                f"Please don't hesitate to email us at success@codecov.io with any questions.",
            ]
        )

    def paginate_annotations(self, annotations):
        for i in range(0, len(annotations), self.ANNOTATIONS_PER_REQUEST):
            yield annotations[i : i + self.ANNOTATIONS_PER_REQUEST]

    async def build_payload(self, comparison) -> Dict[str, str]:
        raise NotImplementedError()

    def get_status_external_name(self) -> str:
        status_piece = f"/{self.title}" if self.title != "default" else ""
        return f"codecov/{self.context}{status_piece}"

    async def notify(self, comparison: Comparison):
        if comparison.pull is None or ():
            log.debug(
                "Faling back to commit_status: Not a pull request",
                extra=dict(
                    notifier=self.name,
                    repoid=comparison.head.commit.repoid,
                    notifier_title=self.title,
                    commit=comparison.head.commit,
                ),
            )
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
            log.debug(
                "Faling back to commit_status: Pull request not in provider",
                extra=dict(
                    notifier=self.name,
                    repoid=comparison.head.commit.repoid,
                    notifier_title=self.title,
                    commit=comparison.head.commit,
                ),
            )
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_not_in_provider",
                data_sent=None,
                data_received=None,
            )
        if comparison.pull.state != "open":
            log.debug(
                "Faling back to commit_status: Pull request closed",
                extra=dict(
                    notifier=self.name,
                    repoid=comparison.head.commit.repoid,
                    notifier_title=self.title,
                    commit=comparison.head.commit,
                ),
            )
            return NotificationResult(
                notification_attempted=False,
                notification_successful=None,
                explanation="pull_request_closed",
                data_sent=None,
                data_received=None,
            )

        payload = None
        filtered_comparison = comparison.get_filtered_comparison(
            **self.get_notifier_filters()
        )
        try:
            with nullcontext():
                payload = await self.build_payload(filtered_comparison)

                # If flag coverage wasn't uploaded, apply the appropriate behavior
                flag_coverage_not_uploaded_behavior = self.determine_status_check_behavior_to_apply(
                    comparison, "flag_coverage_not_uploaded_behavior"
                )
                if (
                    flag_coverage_not_uploaded_behavior != "include"
                    and not self.flag_coverage_was_uploaded(comparison)
                ):
                    log.info(
                        "Status check flag coverage was not uploaded, applying behavior based on YAML settings",
                        extra=dict(
                            commit=comparison.head.commit.commitid,
                            repoid=comparison.head.commit.repoid,
                            notifier_name=self.name,
                            flag_coverage_not_uploaded_behavior=flag_coverage_not_uploaded_behavior,
                        ),
                    )

                    if flag_coverage_not_uploaded_behavior == "pass":
                        payload["state"] = "success"
                        payload["output"]["summary"] = (
                            payload.get("output", {}).get("summary", "")
                            + " [Auto passed due to carriedforward or missing coverage]"
                        )
                    elif flag_coverage_not_uploaded_behavior == "exclude":
                        return NotificationResult(
                            notification_attempted=False,
                            notification_successful=None,
                            explanation="exclude_flag_coverage_not_uploaded_checks",
                            data_sent=None,
                            data_received=None,
                        )
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
        except TorngitClientError as e:
            if e.code == 403:
                raise e
            log.warning(
                "Unable to send checks notification to user due to a client-side error",
                exc_info=True,
                extra=dict(
                    repoid=comparison.head.commit.repoid,
                    commit=comparison.head.commit.commitid,
                    notifier_name=self.name,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="client_side_error_provider",
                data_sent=payload,
            )
        except TorngitError:
            log.warning(
                "Unable to send checks notification to user due to an unexpected error",
                exc_info=True,
                extra=dict(
                    repoid=comparison.head.commit.repoid,
                    commit=comparison.head.commit.commitid,
                    notifier_name=self.name,
                ),
            )
            return NotificationResult(
                notification_attempted=True,
                notification_successful=False,
                explanation="server_side_error_provider",
                data_sent=payload,
            )

    async def get_diff(self, comparison: Comparison):
        return await comparison.get_diff()

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
            header = segment["header"].copy()
            lines = segment["lines"].copy()
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

    @metrics.timer("worker.services.notifications.notifiers.checks.create_annotations")
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

        # Append tracking parameters to any codecov urls in the title or summary
        output = payload.get("output", {})
        if output.get("title"):
            output["title"] = append_tracking_params_to_urls(
                output["title"],
                service=self.repository.service,
                notification_type="checks",
                org_name=self.repository.owner.name,
            )
        if output.get("summary"):
            output["summary"] = append_tracking_params_to_urls(
                output["summary"],
                service=self.repository.service,
                notification_type="checks",
                org_name=self.repository.owner.name,
            )
        if output.get("text"):
            output["text"] = append_tracking_params_to_urls(
                output["text"],
                service=self.repository.service,
                notification_type="checks",
                org_name=self.repository.owner.name,
            )

        # We need to first create the check run, get that id and update the status
        with metrics.timer(
            "worker.services.notifications.notifiers.checks.create_check_run"
        ):
            check_id = await repository_service.create_check_run(
                check_name=title, head_sha=head.commitid
            )

        if len(output.get("annotations", [])) > self.ANNOTATIONS_PER_REQUEST:
            annotation_pages = list(
                self.paginate_annotations(output.get("annotations"))
            )
            log.info(
                "Paginating annotations",
                extra=dict(
                    number_pages=len(annotation_pages),
                    number_annotations=len(output.get("annotations")),
                ),
            )
            for annotation_page in annotation_pages:
                with metrics.timer(
                    "worker.services.notifications.notifiers.checks.update_check_run"
                ):
                    await repository_service.update_check_run(
                        check_id,
                        state,
                        output={
                            "title": output.get("title"),
                            "summary": output.get("summary"),
                            "annotations": annotation_page,
                        },
                    )

        else:
            with metrics.timer(
                "worker.services.notifications.notifiers.checks.update_check_run"
            ):
                await repository_service.update_check_run(
                    check_id, state, output=output
                )

        return NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent=payload,
        )
