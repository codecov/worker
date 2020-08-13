import pytest
from decimal import Decimal
from services.notification.notifiers.comment import CommentNotifier
from services.notification.notifiers.mixins.message import (
    diff_to_string,
    format_number_to_str,
    sort_by_importance,
    Change,
)
from services.decoration import Decoration
from database.tests.factories import RepositoryFactory
from services.notification.notifiers.base import NotificationResult
from shared.reports.types import ReportTotals
from shared.torngit.exceptions import (
    TorngitObjectNotFoundError,
    TorngitServerUnreachableError,
    TorngitClientError,
)


@pytest.fixture
def mock_repo_provider(mock_repo_provider):
    compare_result = {
        "diff": {
            "files": {
                "file_1.go": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["5", "8", "5", "9"],
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        },
                        {
                            "header": ["46", "12", "47", "19"],
                            "lines": [
                                " ",
                                " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                " ",
                                "-We highly suggest adding `source` to your ``.coveragerc`` which solves a number of issues collecting coverage.",
                                "+We highly suggest adding ``source`` to your ``.coveragerc``, which solves a number of issues collecting coverage.",
                                " ",
                                " .. code-block:: ini",
                                " ",
                                "    [run]",
                                "    source=your_package_name",
                                "+   ",
                                "+If there are multiple sources, you instead should add ``include`` to your ``.coveragerc``",
                                "+",
                                "+.. code-block:: ini",
                                "+",
                                "+   [run]",
                                "+   include=your_package_name/*",
                                " ",
                                " unittests",
                                " ---------",
                            ],
                        },
                        {
                            "header": ["150", "5", "158", "4"],
                            "lines": [
                                " * Twitter: `@codecov <https://twitter.com/codecov>`_.",
                                " * Email: `hello@codecov.io <hello@codecov.io>`_.",
                                " ",
                                "-We are happy to help if you have any questions. Please contact email our Support at [support@codecov.io](mailto:support@codecov.io)",
                                "-",
                                "+We are happy to help if you have any questions. Please contact email our Support at `support@codecov.io <mailto:support@codecov.io>`_.",
                            ],
                        },
                    ],
                    "stats": {"added": 11, "removed": 4},
                }
            }
        },
        "commits": [
            {
                "commitid": "{comparison.base.commit[:7]}44fdd29fcc506317cc3ddeae1a723dd08",
                "message": "Update README.rst",
                "timestamp": "2018-07-09T23:51:16Z",
                "author": {
                    "id": 8398772,
                    "username": "jerrode",
                    "name": "Jerrod",
                    "email": "jerrod@fundersclub.com",
                },
            },
            {
                "commitid": "6ae5f1795a441884ed2847bb31154814ac01ef38",
                "message": "Update README.rst",
                "timestamp": "2018-04-26T08:35:58Z",
                "author": {
                    "id": 11602092,
                    "username": "TomPed",
                    "name": "Thomas Pedbereznak",
                    "email": "tom@tomped.com",
                },
            },
        ],
    }
    mock_repo_provider.get_compare.return_value = compare_result
    mock_repo_provider.post_comment.return_value = {}
    mock_repo_provider.edit_comment.return_value = {}
    mock_repo_provider.delete_comment.return_value = {}
    return mock_repo_provider


class TestCommentNotifierHelpers(object):
    def test_sort_by_importance(self):
        modified_change = Change(
            path="modified.py",
            in_diff=True,
            totals=ReportTotals(
                files=0,
                lines=0,
                hits=-2,
                misses=1,
                partials=0,
                coverage=-23.333330000000004,
                branches=0,
                methods=0,
                messages=0,
                sessions=0,
                complexity=0,
                complexity_total=0,
                diff=0,
            ),
        )
        renamed_with_changes_change = Change(
            path="renamed_with_changes.py",
            in_diff=True,
            old_path="old_renamed_with_changes.py",
            totals=ReportTotals(
                files=0,
                lines=0,
                hits=-1,
                misses=1,
                partials=0,
                coverage=-20.0,
                branches=0,
                methods=0,
                messages=0,
                sessions=0,
                complexity=0,
                complexity_total=0,
                diff=0,
            ),
        )
        unrelated_change = Change(
            path="unrelated.py",
            in_diff=False,
            totals=ReportTotals(
                files=0,
                lines=0,
                hits=-3,
                misses=2,
                partials=0,
                coverage=-43.333330000000004,
                branches=0,
                methods=0,
                messages=0,
                sessions=0,
                complexity=0,
                complexity_total=0,
                diff=0,
            ),
        )
        added_change = Change(
            path="added.py", new=True, in_diff=None, old_path=None, totals=None
        )
        deleted_change = Change(path="deleted.py", deleted=True)
        changes = [
            modified_change,
            renamed_with_changes_change,
            unrelated_change,
            added_change,
            deleted_change,
        ]
        res = sort_by_importance(changes)
        expected_result = [
            unrelated_change,
            modified_change,
            renamed_with_changes_change,
            deleted_change,
            added_change,
        ]
        assert expected_result == res

    def test_format_number_to_str(self):
        assert "<0.1" == format_number_to_str(
            {"coverage": {"precision": 1}}, Decimal("0.001")
        )
        assert "10.0" == format_number_to_str(
            {"coverage": {"precision": 1}}, Decimal("10.001")
        )
        assert "10.1" == format_number_to_str(
            {"coverage": {"precision": 1, "round": "up"}}, Decimal("10.001")
        )

    def test_diff_to_string_case_1(self):
        case_1 = (
            "master",
            ReportTotals(10),
            "stable",
            ReportTotals(11),
            [
                "@@         Coverage Diff          @@",
                "##        master   stable   +/-   ##",
                "====================================",
                "====================================",
                "  Files       10       11    +1     ",
                "",
            ],
        )
        case = case_1
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result

    def test_diff_to_string_case_2(self):
        case_2 = (
            "master",
            ReportTotals(files=10, coverage="12.0", complexity="10.0"),
            "stable",
            ReportTotals(files=10, coverage="15.0", complexity="9.0"),
            [
                "@@             Coverage Diff              @@",
                "##             master   stable      +/-   ##",
                "============================================",
                "+ Coverage     12.00%   15.00%   +3.00%     ",
                "- Complexity   10.00%    9.00%   -1.00%     ",
                "============================================",
                "  Files            10       10              ",
                "",
            ],
        )
        case = case_2
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result

    def test_diff_to_string_case_3(self):
        case_3 = (
            "master",
            ReportTotals(files=100),
            "#1",
            ReportTotals(files=200, lines=2, hits=6, misses=7, partials=8, branches=3),
            [
                "@@          Coverage Diff          @@",
                "##           master    #1    +/-   ##",
                "=====================================",
                "=====================================",
                "  Files         100   200   +100     ",
                "  Lines           0     2     +2     ",
                "  Branches        0     3     +3     ",
                "=====================================",
                "+ Hits            0     6     +6     ",
                "- Misses          0     7     +7     ",
                "- Partials        0     8     +8     ",
            ],
        )
        case = case_3
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result

    def test_diff_to_string_case_4(self):
        case_4 = (
            "master",
            ReportTotals(files=10, coverage="12.0", complexity=10),
            "stable",
            ReportTotals(files=10, coverage="15.0", complexity=9),
            [
                "@@             Coverage Diff              @@",
                "##             master   stable      +/-   ##",
                "============================================",
                "+ Coverage     12.00%   15.00%   +3.00%     ",
                "+ Complexity       10        9       -1     ",
                "============================================",
                "  Files            10       10              ",
                "",
            ],
        )
        case = case_4
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result


class TestCommentNotifier(object):
    @pytest.mark.asyncio
    async def test_is_enabled_settings_individual_settings_false(self, dbsession):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        notifier = CommentNotifier(
            repository=repository,
            title="some_title",
            notifier_yaml_settings=False,
            notifier_site_settings=None,
            current_yaml={},
        )
        assert not notifier.is_enabled()

    @pytest.mark.asyncio
    async def test_is_enabled_settings_individual_settings_none(self, dbsession):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        notifier = CommentNotifier(
            repository=repository,
            title="some_title",
            notifier_yaml_settings=None,
            notifier_site_settings=None,
            current_yaml={},
        )
        assert not notifier.is_enabled()

    @pytest.mark.asyncio
    async def test_is_enabled_settings_individual_settings_true(self, dbsession):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        notifier = CommentNotifier(
            repository=repository,
            title="some_title",
            notifier_yaml_settings=True,
            notifier_site_settings=None,
            current_yaml={},
        )
        assert not notifier.is_enabled()

    @pytest.mark.asyncio
    async def test_is_enabled_settings_individual_settings_dict(self, dbsession):
        repository = RepositoryFactory.create()
        dbsession.add(repository)
        dbsession.flush()
        notifier = CommentNotifier(
            repository=repository,
            title="some_title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=None,
            current_yaml={},
        )
        assert notifier.is_enabled()

    def test_create_message_files_section(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        comparison = sample_comparison
        diff = {
            "files": {
                "file_1.go": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["105", "8", "105", "9"],
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        },
                        {
                            "header": ["1046", "12", "1047", "19"],
                            "lines": [
                                " ",
                                " You may need to configure a ``.coveragerc`` file. Learn more",
                                " ",
                                "-We highly suggest adding `source` to your ``.coveragerc``",
                                "+We highly suggest adding ``source`` to your ``.coveragerc`",
                                " ",
                                " .. code-block:: ini",
                                " ",
                                "    [run]",
                                "    source=your_package_name",
                                "+   ",
                                "+If there are multiple sources, you instead should add ``include",
                                "+",
                                "+.. code-block:: ini",
                                "+",
                                "+   [run]",
                                "+   include=your_package_name/*",
                                " ",
                                " unittests",
                                " ---------",
                            ],
                        },
                        {
                            "header": ["10150", "5", "10158", "4"],
                            "lines": [
                                " * Twitter: `@codecov <https://twitter.com/codecov>`_.",
                                " * Email: `hello@codecov.io <hello@codecov.io>`_.",
                                " ",
                                "-We are happy to help if you have any questions. ",
                                "-",
                                "+We are happy to help if you have any questions. .",
                            ],
                        },
                    ],
                    "stats": {"added": 11, "removed": 4},
                },
                "file_2.py": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["10", "8", "10", "9"],
                            "lines": [
                                " Overview",
                                " --------",
                                " ",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "-Main website: `Codecov <https://codecov.io/>`_.",
                                "+",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                "+website: `Codecov <https://codecov.io/>`_.",
                                " ",
                                " .. code-block:: shell-session",
                                " ",
                            ],
                        },
                        {
                            "header": ["50", "12", "51", "19"],
                            "lines": [
                                " ",
                                " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                " ",
                                "-We highly suggest adding `source` to your ``.coveragerc`` which solves a number of issues collecting coverage.",
                                "+We highly suggest adding ``source`` to your ``.coveragerc``, which solves a number of issues collecting coverage.",
                                " ",
                                " .. code-block:: ini",
                                " ",
                                "    [run]",
                                "    source=your_package_name",
                                "+   ",
                                "+If there are multiple sources, you instead should add ``include`` to your ``.coveragerc``",
                                "+",
                                "+.. code-block:: ini",
                                "+",
                                "+   [run]",
                                "+   include=your_package_name/*",
                                " ",
                                " unittests",
                                " ---------",
                            ],
                        },
                    ],
                    "stats": {"added": 11, "removed": 4},
                },
            }
        }
        pull_dict = {"base": {"branch": "master"}}
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "files"},
            notifier_site_settings=True,
            current_yaml={},
        )
        pull = comparison.pull
        repository = sample_comparison.head.commit.repository
        expected_result = [
            f"# [Codecov](https://codecov.io/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](https://codecov.io/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](https://codecov.io/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `n/a`.",
            f"",
            f"| [Impacted Files](https://codecov.io/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\\_1.go](https://codecov.io/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <ø> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
            f"| [file\\_2.py](https://codecov.io/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <ø> (ø)` | `0.00 <0.00> (ø)` | |",
            f"",
        ]
        res = notifier.create_message(comparison, diff, pull_dict, {"layout": "files"})
        print(res)
        assert expected_result == res

    @pytest.mark.asyncio
    async def test_build_message(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = sample_comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `66.67%`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@              Coverage Diff              @@",
            f"##             master      #{pull.pullid}       +/-   ##",
            f"=============================================",
            f"+ Coverage     50.00%   60.00%   +10.00%     ",
            f"+ Complexity       11       10        -1     ",
            f"=============================================",
            f"  Files             2        2               ",
            f"  Lines             6       10        +4     ",
            f"  Branches          0        1        +1     ",
            f"=============================================",
            f"+ Hits              3        6        +3     ",
            f"  Misses            3        3               ",
            f"- Partials          0        1        +1     ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #integration | `?` | `?` | |",
            f"| #unit | `100.00% <100.00%> (?)` | `0.00 <0.00> (?)` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{sample_comparison.base.commit.commitid[:7]}...{sample_comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_upgrade_message(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison
        pull = comparison.enriched_pull.database_pull
        repository = sample_comparison.head.commit.repository
        notifier = CommentNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
            decoration_type=Decoration.upgrade,
        )
        result = await notifier.build_message(comparison)
        provider_pull = comparison.enriched_pull.provider_pull
        expected_result = [
            f"The author of this PR, {provider_pull['author']['username']}, is not an activated member of this organization on Codecov.",
            f"Please [activate this user on Codecov](test.example.br/account/gh/{pull.repository.owner.username}/users) to display this PR comment.",
            f"Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
            f"Please don't hesitate to email us at success@codecov.io with any questions.",
        ]
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_hide_complexity(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={"codecov": {"ui": {"hide_complexity": True}}},
        )
        repository = sample_comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `66.67%`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@              Coverage Diff              @@",
            f"##             master      #{pull.pullid}       +/-   ##",
            f"=============================================",
            f"+ Coverage     50.00%   60.00%   +10.00%     ",
            f"+ Complexity       11       10        -1     ",
            f"=============================================",
            f"  Files             2        2               ",
            f"  Lines             6       10        +4     ",
            f"  Branches          0        1        +1     ",
            f"=============================================",
            f"+ Hits              3        6        +3     ",
            f"  Misses            3        3               ",
            f"- Partials          0        1        +1     ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | |",
            f"|---|---|---|",
            f"| #integration | `?` | |",
            f"| #unit | `100.00% <100.00%> (?)` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | |",
            f"|---|---|---|",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | :arrow_up: |",
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{sample_comparison.base.commit.commitid[:7]}...{sample_comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_no_base_report(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_comparison_without_base_report,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> :exclamation: No coverage uploaded for pull request base (`master@{comparison.base.commit.commitid[:7]}`). [Click here to learn what that means](https://docs.codecov.io/docs/error-reference#section-missing-base-commit).",
            f"> The diff coverage is `66.67%`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@            Coverage Diff            @@",
            f"##             master      #{pull.pullid}   +/-   ##",
            f"=========================================",
            f"  Coverage          ?   60.00%           ",
            f"  Complexity        ?       10           ",
            f"=========================================",
            f"  Files             ?        2           ",
            f"  Lines             ?       10           ",
            f"  Branches          ?        1           ",
            f"=========================================",
            f"  Hits              ?        6           ",
            f"  Misses            ?        3           ",
            f"  Partials          ?        1           ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #unit | `100.00% <100.00%> (?)` | `0.00 <0.00> (?)` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (ø)` | `10.00 <0.00> (?)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{comparison.base.commit.commitid[:7]}...{comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        for exp, res in zip(expected_result, result):
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_no_base_commit(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_comparison_without_base_with_pull,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_without_base_with_pull
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> :exclamation: No coverage uploaded for pull request base (`master@cdf9aa4`). [Click here to learn what that means](https://docs.codecov.io/docs/error-reference#section-missing-base-commit).",
            f"> The diff coverage is `n/a`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@            Coverage Diff            @@",
            f"##             master      #{pull.pullid}   +/-   ##",
            f"=========================================",
            f"  Coverage          ?   60.00%           ",
            f"  Complexity        ?       10           ",
            f"=========================================",
            f"  Files             ?        2           ",
            f"  Lines             ?       10           ",
            f"  Branches          ?        1           ",
            f"=========================================",
            f"  Hits              ?        6           ",
            f"  Misses            ?        3           ",
            f"  Partials          ?        1           ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #unit | `100.00% <0.00%> (?)` | `0.00% <0.00%> (?%)` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[cdf9aa4...{comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        for exp, res in zip(expected_result, result):
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_no_change(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_comparison_no_change,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_no_change
        pull = comparison.pull

        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)

        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{comparison.base.commit.commitid}&el=desc) will **not change** coverage.",
            f"> The diff coverage is `66.67%`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@            Coverage Diff            @@",
            f"##             master      #{pull.pullid}   +/-   ##",
            f"=========================================",
            f"  Coverage     60.00%   60.00%           ",
            f"  Complexity       10       10           ",
            f"=========================================",
            f"  Files             2        2           ",
            f"  Lines            10       10           ",
            f"  Branches          1        1           ",
            f"=========================================",
            f"  Hits              6        6           ",
            f"  Misses            3        3           ",
            f"  Partials          1        1           ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #unit | `100.00% <100.00%> (ø)` | `0.00 <0.00> (ø)` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (ø)` | `10.00 <0.00> (ø)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{sample_comparison_no_change.base.commit.commitid[:7]}...{sample_comparison_no_change.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        print(result)
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_negative_change(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_comparison_negative_change,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_negative_change
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{comparison.base.commit.commitid}&el=desc) will **decrease** coverage by `10.00%`.",
            f"> The diff coverage is `n/a`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@              Coverage Diff              @@",
            f"##             master      #{pull.pullid}       +/-   ##",
            f"=============================================",
            f"- Coverage     60.00%   50.00%   -10.00%     ",
            f"- Complexity       10       11        +1     ",
            f"=============================================",
            f"  Files             2        2               ",
            f"  Lines            10        6        -4     ",
            f"  Branches          1        0        -1     ",
            f"=============================================",
            f"- Hits              6        3        -3     ",
            f"  Misses            3        3               ",
            f"+ Partials          1        0        -1     ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #integration | `100.00% <ø> (?)` | `0.00 <ø> (?)` | |",
            f"| #unit | `?` | `?` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `50.00% <ø> (-12.50%)` | `11.00 <0.00> (+1.00)` | :arrow_down: |",
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{comparison.base.commit.commitid[:7]}...{comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        print(result)
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_show_carriedforward_flags_no_cf_coverage(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "show_carryforward_flags": True,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `66.67%`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@              Coverage Diff              @@",
            f"##             master      #{pull.pullid}       +/-   ##",
            f"=============================================",
            f"+ Coverage     50.00%   60.00%   +10.00%     ",
            f"+ Complexity       11       10        -1     ",
            f"=============================================",
            f"  Files             2        2               ",
            f"  Lines             6       10        +4     ",
            f"  Branches          0        1        +1     ",
            f"=============================================",
            f"+ Hits              3        6        +3     ",
            f"  Misses            3        3               ",
            f"- Partials          0        1        +1     ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #integration | `?` | `?` | |",
            f"| #unit | `100.00% <100.00%> (?)` | `0.00 <0.00> (?)` | |",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{sample_comparison.base.commit.commitid[:7]}...{sample_comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        print(result)
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_show_carriedforward_flags_has_cf_coverage(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_comparison_coverage_carriedforward,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_coverage_carriedforward
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "show_carryforward_flags": True,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{comparison.base.commit.commitid}&el=desc) will **not change** coverage.",
            f"> The diff coverage is `n/a`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@           Coverage Diff           @@",
            f"##           master      #{pull.pullid}   +/-   ##",
            f"=======================================",
            f"  Coverage   65.38%   65.38%           ",
            f"=======================================",
            f"  Files          15       15           ",
            f"  Lines         208      208           ",
            f"=======================================",
            f"  Hits          136      136           ",
            f"  Misses          4        4           ",
            f"  Partials       68       68           ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | | *Carryforward flag |",
            f"|---|---|---|---|",
            f"| #enterprise | `25.00% <ø> (ø)` | | Carriedforward from [1234567](test.example.br/gh/{repository.slug}/commit/123456789sha) |",
            f"| #integration | `25.00% <ø> (ø)` | | Carriedforward |",
            f"| #unit | `25.00% <ø> (ø)` | | |",
            f"",
            f"*This pull request uses carry forward flags. [Click here](https://docs.codecov.io/docs/carryforward-flags) to find out more."
            f"",
            f"",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{comparison.base.commit.commitid[:7]}...{comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        print(result)
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_hide_carriedforward_flags_has_cf_coverage(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_comparison_coverage_carriedforward,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        comparison = sample_comparison_coverage_carriedforward
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "show_carryforward_flags": False,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{comparison.base.commit.commitid}&el=desc) will **not change** coverage.",
            f"> The diff coverage is `n/a`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@           Coverage Diff           @@",
            f"##           master      #{pull.pullid}   +/-   ##",
            f"=======================================",
            f"  Coverage   65.38%   65.38%           ",
            f"=======================================",
            f"  Files          15       15           ",
            f"  Lines         208      208           ",
            f"=======================================",
            f"  Hits          136      136           ",
            f"  Misses          4        4           ",
            f"  Partials       68       68           ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | |",
            f"|---|---|---|",
            f"| #unit | `25.00% <ø> (ø)` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more."
            f"",
            f"",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{comparison.base.commit.commitid[:7]}...{comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        print(result)
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_send_actual_notification_spammy(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "spammy",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": 9865}
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        assert not mock_repo_provider.edit_comment.called
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_build_message_no_flags(
        self,
        dbsession,
        mock_configuration,
        mock_repo_provider,
        sample_report_without_flags,
        sample_comparison,
    ):
        mock_configuration.params["setup"]["codecov_url"] = "test.example.br"
        pull = sample_comparison.pull
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"layout": "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={},
        )
        sample_comparison.head.report = sample_report_without_flags
        comparison = sample_comparison
        repository = sample_comparison.head.commit.repository
        result = await notifier.build_message(sample_comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `66.67%`.",
            f"",
            f"[![Impacted file tree graph](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/graphs/tree.svg?width=650&height=150&src=pr&token={repository.image_token})](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree)",
            f"",
            f"```diff",
            f"@@              Coverage Diff              @@",
            f"##             master      #{pull.pullid}       +/-   ##",
            f"=============================================",
            f"+ Coverage     50.00%   60.00%   +10.00%     ",
            f"+ Complexity       11       10        -1     ",
            f"=============================================",
            f"  Files             2        2               ",
            f"  Lines             6       10        +4     ",
            f"  Branches          0        1        +1     ",
            f"=============================================",
            f"+ Hits              3        6        +3     ",
            f"  Misses            3        3               ",
            f"- Partials          0        1        +1     ",
            f"```",
            f"",
            f"| Flag | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| #integration | `?` | `?` | |",
            f"",
            f"Flags with carried forward coverage won't be shown. [Click here](https://docs.codecov.io/docs/carryforward-flags#carryforward-flags-in-the-pull-request-comment) to find out more.",
            f"",
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | Complexity Δ | |",
            f"|---|---|---|---|",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <66.67%> (+12.50%)` | `10.00 <0.00> (-1.00)` | :arrow_up: |",
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | |",
            f"",
            f"------",
            f"",
            f"[Continue to review full report at "
            f"Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).",
            f"> **Legend** - [Click here to learn "
            f"more](https://docs.codecov.io/docs/codecov-delta)",
            f"> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`",
            f"> Powered by "
            f"[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). "
            f"Last update "
            f"[{comparison.base.commit.commitid[:7]}...{comparison.head.commit.commitid[:7]}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). "
            f"Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).",
            f"",
        ]
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_send_actual_notification_new_no_permissions(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "new",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.delete_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "no_permissions"
        assert result.data_sent == data
        assert result.data_received is None
        mock_repo_provider.delete_comment.assert_called_with(98, "12345")
        assert not mock_repo_provider.post_comment.called
        assert not mock_repo_provider.edit_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_new(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "new",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.delete_comment.return_value = True
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": 9865}
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        assert not mock_repo_provider.edit_comment.called
        mock_repo_provider.delete_comment.assert_called_with(98, "12345")

    @pytest.mark.asyncio
    async def test_send_actual_notification_new_no_permissions_post(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "new",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": None, "pullid": 98}
        mock_repo_provider.post_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        mock_repo_provider.edit_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "comment_posting_permissions"
        assert result.data_sent == data
        assert result.data_received is None
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        assert not mock_repo_provider.delete_comment.called
        assert not mock_repo_provider.edit_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_new_deleted_comment(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "new",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.delete_comment.side_effect = TorngitObjectNotFoundError(
            "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": 9865}
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        assert not mock_repo_provider.edit_comment.called
        mock_repo_provider.delete_comment.assert_called_with(98, "12345")

    @pytest.mark.asyncio
    async def test_send_actual_notification_once_deleted_comment(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "once",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.side_effect = TorngitObjectNotFoundError(
            "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "comment_deleted"
        assert result.data_sent == data
        assert result.data_received is None
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_once_non_existing_comment(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "once",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": None, "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.side_effect = TorngitObjectNotFoundError(
            "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": 9865}
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        assert not mock_repo_provider.delete_comment.called
        assert not mock_repo_provider.edit_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_once(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "once",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.return_value = {"id": "49"}
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": "49"}
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_once_no_permissions(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "once",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "no_permissions"
        assert result.data_sent == data
        assert result.data_received is None
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_default(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.return_value = {"id": "49"}
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": "49"}
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_default_no_permissions_edit(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": 9865}
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_default_no_permissions_twice(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        mock_repo_provider.edit_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "comment_posting_permissions"
        assert result.data_sent == data
        assert result.data_received is None
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_default_comment_not_found(
        self, dbsession, mock_configuration, mock_repo_provider, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        data = {"message": ["message"], "commentid": "12345", "pullid": 98}
        mock_repo_provider.post_comment.return_value = {"id": 9865}
        mock_repo_provider.edit_comment.side_effect = TorngitObjectNotFoundError(
            "response", "message"
        )
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {"id": 9865}
        mock_repo_provider.edit_comment.assert_called_with(98, "12345", "message")
        mock_repo_provider.post_comment.assert_called_with(98, "message")
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_notify_no_pull_request(
        self, dbsession, sample_comparison_without_pull
    ):
        notifier = CommentNotifier(
            repository=sample_comparison_without_pull.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison_without_pull)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "no_pull_request"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_pull_request_not_in_provider(
        self, dbsession, sample_comparison_database_pull_without_provider
    ):
        notifier = CommentNotifier(
            repository=sample_comparison_database_pull_without_provider.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison_database_pull_without_provider)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "pull_request_not_in_provider"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_server_unreachable(
        self, mocker, dbsession, sample_comparison
    ):
        mocked_send_actual_notification = mocker.patch.object(
            CommentNotifier,
            "send_actual_notification",
            side_effect=TorngitServerUnreachableError(),
        )
        mocked_build_message = mocker.patch.object(
            CommentNotifier, "build_message", return_value=["title", "content"]
        )
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == "provider_issue"
        assert result.data_sent == {
            "commentid": None,
            "message": ["title", "content"],
            "pullid": sample_comparison.pull.pullid,
        }
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_store_results(self, dbsession, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent=None,
            data_received={"id": 578263422},
        )
        notifier.store_results(sample_comparison, result)
        assert sample_comparison.pull.commentid == 578263422
        dbsession.flush()
        assert sample_comparison.pull.commentid == 578263422
        dbsession.refresh(sample_comparison.pull)
        assert sample_comparison.pull.commentid == "578263422"

    @pytest.mark.asyncio
    async def test_store_results_deleted_comment(self, dbsession, sample_comparison):
        sample_comparison.pull.commentid = 12
        dbsession.flush()
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent=None,
            data_received={"deleted_comment": True},
        )
        notifier.store_results(sample_comparison, result)
        assert sample_comparison.pull.commentid is None
        dbsession.flush()
        assert sample_comparison.pull.commentid is None
        dbsession.refresh(sample_comparison.pull)
        assert sample_comparison.pull.commentid is None

    @pytest.mark.asyncio
    async def test_store_results_no_succesfull_result(
        self, dbsession, sample_comparison
    ):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = NotificationResult(
            notification_attempted=True,
            notification_successful=False,
            explanation=None,
            data_sent=None,
            data_received={"id": "yadayada"},
        )
        notifier.store_results(sample_comparison, result)
        assert sample_comparison.pull.commentid is None
        dbsession.flush()
        assert sample_comparison.pull.commentid is None
        dbsession.refresh(sample_comparison.pull)
        assert sample_comparison.pull.commentid is None

    @pytest.mark.asyncio
    async def test_notify_closed_pull_request(self, dbsession, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        sample_comparison.pull.state = "closed"
        dbsession.flush()
        dbsession.refresh(sample_comparison.pull)
        result = await notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "pull_request_closed"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_unable_to_fetch_info(
        self, dbsession, mocker, sample_comparison
    ):
        mocked_build_message = mocker.patch.object(
            CommentNotifier,
            "build_message",
            side_effect=TorngitClientError("code", "response", "message"),
        )
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "unable_build_message"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_not_enough_builds(self, dbsession, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 5,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == "not_enough_builds"
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_notify_with_enough_builds(
        self, dbsession, sample_comparison, mocker
    ):
        build_message_mocker = mocker.patch.object(
            CommentNotifier,
            "build_message",
            return_value="message_test_notify_with_enough_builds",
        )
        send_comment_default_behavior_mocker = mocker.patch.object(
            CommentNotifier,
            "send_comment_default_behavior",
            return_value=dict(
                notification_attempted=True,
                notification_successful=True,
                explanation=None,
                data_received=None,
            ),
        )
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        result = await notifier.notify(sample_comparison)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == {
            "commentid": None,
            "message": "message_test_notify_with_enough_builds",
            "pullid": sample_comparison.pull.pullid,
        }
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_has_enough_changes(self, sample_comparison, mock_repo_provider):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        assert await notifier.has_enough_changes(sample_comparison)

    @pytest.mark.asyncio
    async def test_has_enough_changes_exact_same_report_diff_intersection_report(
        self, sample_comparison_no_change, mock_repo_provider
    ):
        notifier = CommentNotifier(
            repository=sample_comparison_no_change.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        assert await notifier.has_enough_changes(sample_comparison_no_change)

    @pytest.mark.asyncio
    async def test_has_enough_changes_exact_same_report_diff_unrelated_report(
        self, sample_comparison_no_change, mock_repo_provider
    ):
        compare_result = {
            "diff": {
                "files": {
                    "README.md": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["5", "8", "5", "9"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            },
                            {
                                "header": ["46", "12", "47", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                    " -",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_repo_provider.get_compare.return_value = compare_result
        notifier = CommentNotifier(
            repository=sample_comparison_no_change.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        assert not (await notifier.has_enough_changes(sample_comparison_no_change))

    @pytest.mark.asyncio
    async def test_notify_exact_same_report_diff_unrelated_report(
        self, sample_comparison_no_change, mock_repo_provider
    ):
        compare_result = {
            "diff": {
                "files": {
                    "README.md": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["5", "8", "5", "9"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            },
                            {
                                "header": ["46", "12", "47", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                    " -",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_repo_provider.get_compare.return_value = compare_result
        notifier = CommentNotifier(
            repository=sample_comparison_no_change.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
                "require_changes": True,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        res = await notifier.notify(sample_comparison_no_change)
        assert res.notification_attempted is False
        assert res.notification_successful is None
        assert res.explanation == "changes_required"
        assert res.data_sent is None
        assert res.data_received is None

    @pytest.mark.asyncio
    async def test_notify_exact_same_report_diff_unrelated_report_deleting_comment(
        self, sample_comparison_no_change, mock_repo_provider
    ):
        compare_result = {
            "diff": {
                "files": {
                    "README.md": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["5", "8", "5", "9"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            },
                            {
                                "header": ["46", "12", "47", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                    " -",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_repo_provider.get_compare.return_value = compare_result
        sample_comparison_no_change.pull.commentid = 12
        notifier = CommentNotifier(
            repository=sample_comparison_no_change.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
                "require_changes": True,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        res = await notifier.notify(sample_comparison_no_change)
        assert res.notification_attempted is False
        assert res.notification_successful is None
        assert res.explanation == "changes_required"
        assert res.data_sent is None
        assert res.data_received == {"deleted_comment": True}

    @pytest.mark.asyncio
    async def test_notify_exact_same_report_diff_unrelated_report_deleting_comment_cant_delete(
        self, sample_comparison_no_change, mock_repo_provider
    ):
        compare_result = {
            "diff": {
                "files": {
                    "README.md": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["5", "8", "5", "9"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            },
                            {
                                "header": ["46", "12", "47", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                    " -",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            }
        }
        mock_repo_provider.get_compare.return_value = compare_result
        mock_repo_provider.delete_comment.side_effect = TorngitClientError(
            "code", "response", "message"
        )
        sample_comparison_no_change.pull.commentid = 12
        notifier = CommentNotifier(
            repository=sample_comparison_no_change.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "layout": "reach, diff, flags, files, footer",
                "behavior": "default",
                "after_n_builds": 1,
                "require_changes": True,
            },
            notifier_site_settings=True,
            current_yaml={},
        )
        res = await notifier.notify(sample_comparison_no_change)
        assert res.notification_attempted is False
        assert res.notification_successful is None
        assert res.explanation == "changes_required"
        assert res.data_sent is None
        assert res.data_received == {"deleted_comment": False}
