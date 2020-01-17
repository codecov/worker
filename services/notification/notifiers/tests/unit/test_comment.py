import pytest
from asyncio import Future
from decimal import Decimal
from services.notification.notifiers.comment import (
    CommentNotifier, diff_to_string, format_number_to_str
)
from covreports.utils.tuples import ReportTotals
from torngit.exceptions import TorngitObjectNotFoundError


@pytest.fixture
def mock_repo_provider(mock_repo_provider):
    result = Future()
    pull_result = Future()
    compare_result = {
        'diff': {
            'files': {
                'file_1.go': {
                    'type': 'modified',
                    'before': None,
                    'segments': [
                        {
                            'header': ['5', '8', '5', '9'],
                            'lines': [
                                ' Overview',
                                ' --------',
                                ' ',
                                '-Main website: `Codecov <https://codecov.io/>`_.',
                                '-Main website: `Codecov <https://codecov.io/>`_.',
                                '+',
                                '+website: `Codecov <https://codecov.io/>`_.',
                                '+website: `Codecov <https://codecov.io/>`_.',
                                ' ',
                                ' .. code-block:: shell-session',
                                ' '
                            ]
                        },
                        {
                            'header': ['46', '12', '47', '19'],
                            'lines': [
                                ' ',
                                ' You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.',
                                ' ',
                                '-We highly suggest adding `source` to your ``.coveragerc`` which solves a number of issues collecting coverage.',
                                '+We highly suggest adding ``source`` to your ``.coveragerc``, which solves a number of issues collecting coverage.',
                                ' ',
                                ' .. code-block:: ini',
                                ' ',
                                '    [run]',
                                '    source=your_package_name',
                                '+   ',
                                '+If there are multiple sources, you instead should add ``include`` to your ``.coveragerc``',
                                '+',
                                '+.. code-block:: ini',
                                '+',
                                '+   [run]',
                                '+   include=your_package_name/*',
                                ' ',
                                ' unittests',
                                ' ---------'
                            ]
                        },
                        {
                            'header': ['150', '5', '158', '4'],
                            'lines': [
                                ' * Twitter: `@codecov <https://twitter.com/codecov>`_.',
                                ' * Email: `hello@codecov.io <hello@codecov.io>`_.',
                                ' ',
                                '-We are happy to help if you have any questions. Please contact email our Support at [support@codecov.io](mailto:support@codecov.io)',
                                '-',
                                '+We are happy to help if you have any questions. Please contact email our Support at `support@codecov.io <mailto:support@codecov.io>`_.'
                            ]
                        }
                    ],
                    'stats': {'added': 11, 'removed': 4}
                }
            }
        },
        'commits': [
            {
                'commitid': 'b92edba44fdd29fcc506317cc3ddeae1a723dd08',
                'message': 'Update README.rst',
                'timestamp': '2018-07-09T23:51:16Z',
                'author': {
                    'id': 8398772,
                    'username': 'jerrode',
                    'name': 'Jerrod',
                    'email': 'jerrod@fundersclub.com'}
            },
            {
                'commitid': '6ae5f1795a441884ed2847bb31154814ac01ef38',
                'message': 'Update README.rst',
                'timestamp': '2018-04-26T08:35:58Z',
                'author': {
                    'id': 11602092,
                    'username': 'TomPed',
                    'name': 'Thomas Pedbereznak',
                    'email': 'tom@tomped.com'
                }
            }
        ]
    }
    pull_result_dict = {
        'base': {
            'branch': 'master',
            'commitid': 'b92edba44fdd29fcc506317cc3ddeae1a723dd08'
        },
        'head': {
            'branch': 'reason/some-testing',
            'commitid': 'a06aef4356ca35b34c5486269585288489e578db'
        },
        'number': '1',
        'id': '1',
        'state': 'open',
        'title': 'Creating new code for reasons no one knows',
    }
    result.set_result(compare_result)
    pull_result.set_result(pull_result_dict)
    mock_repo_provider.get_compare.return_value = result
    mock_repo_provider.get_pull_request.return_value = pull_result
    mock_repo_provider.post_comment.return_value = Future()
    mock_repo_provider.edit_comment.return_value = Future()
    mock_repo_provider.delete_comment.return_value = Future()
    return mock_repo_provider


class TestCommentNotifierHelpers(object):

    def test_format_number_to_str(self):
        assert '<0.1' == format_number_to_str({'coverage': {'precision': 1}}, Decimal('0.001'))
        assert '10.0' == format_number_to_str({'coverage': {'precision': 1}}, Decimal('10.001'))
        assert '10.1' == format_number_to_str({'coverage': {'precision': 1, 'round': 'up'}}, Decimal('10.001'))

    def test_diff_to_string_case_1(self):
        case_1 = (
            'master', ReportTotals(10),
            'stable', ReportTotals(11),
            [
                '@@         Coverage Diff          @@',
                '##        master   stable   +/-   ##',
                '====================================',
                '====================================',
                '  Files       10       11    +1     ',
                ''
            ]
        )
        case = case_1
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result

    def test_diff_to_string_case_2(self):
        case_2 = (
            'master',
            ReportTotals(files=10, coverage='12.0', complexity='10.0'),
            'stable',
            ReportTotals(files=10, coverage='15.0', complexity='9.0'),
            [
                '@@             Coverage Diff              @@',
                '##             master   stable      +/-   ##',
                '============================================',
                '+ Coverage     12.00%   15.00%   +3.00%     ',
                '- Complexity   10.00%    9.00%   -1.00%     ',
                '============================================',
                '  Files            10       10              ',
                ''
            ]
        )
        case = case_2
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result

    def test_diff_to_string_case_3(self):
        case_3 = (
            'master',
            ReportTotals(files=100),
            '#1',
            ReportTotals(
                files=200, lines=2, hits=6,
                misses=7, partials=8, branches=3
            ),
            [
                '@@          Coverage Diff          @@',
                '##           master    #1    +/-   ##',
                '=====================================',
                '=====================================',
                '  Files         100   200   +100     ',
                '  Lines           0     2     +2     ',
                '  Branches        0     3     +3     ',
                '=====================================',
                '+ Hits            0     6     +6     ',
                '- Misses          0     7     +7     ',
                '- Partials        0     8     +8     '
            ]
        )
        case = case_3
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result

    def test_diff_to_string_case_4(self):
        case_4 = (
            'master',
            ReportTotals(files=10, coverage='12.0', complexity=10),
            'stable',
            ReportTotals(files=10, coverage='15.0', complexity=9),
            [
                '@@             Coverage Diff              @@',
                '##             master   stable      +/-   ##',
                '============================================',
                '+ Coverage     12.00%   15.00%   +3.00%     ',
                '+ Complexity       10        9       -1     ',
                '============================================',
                '  Files            10       10              ',
                ''
            ]
        )
        case = case_4
        base_title, base_totals, head_title, head_totals, expected_result = case
        diff = diff_to_string({}, base_title, base_totals, head_title, head_totals)
        assert diff == expected_result


class TestCommentNotifier(object):

    @pytest.mark.asyncio
    async def test_build_message(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'layout': "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={}
        )
        repository = sample_comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `n/a`.",
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
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | `0.00% <0.00%> (ø%)` | :arrow_up: |",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <0.00%> (+12.50%)` | `10.00% <0.00%> (-1.00%)` | :arrow_up: |",
            f'',
            f'------',
            f'',
            f'[Continue to review full report at '
            f'Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).',
            f'> **Legend** - [Click here to learn '
            f'more](https://docs.codecov.io/docs/codecov-delta)',
            f'> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`',
            f'> Powered by '
            f'[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). '
            f'Last update '
            f'[b92edba...a06aef4](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). '
            f'Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).',
            f""
        ]
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_hide_complexity(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'layout': "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={'codecov': {'ui': {'hide_complexity': True}}}
        )
        repository = sample_comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> Merging [#{pull.pullid}](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=desc) into [master](test.example.br/gh/{repository.slug}/commit/{sample_comparison.base.commit.commitid}&el=desc) will **increase** coverage by `10.00%`.",
            f"> The diff coverage is `n/a`.",
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
            f"| [Impacted Files](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=tree) | Coverage Δ | |",
            f"|---|---|---|",
            f"| [file\\_2.py](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8yLnB5) | `50.00% <0.00%> (ø)` | :arrow_up: |",
            f"| [file\\_1.go](test.example.br/gh/{repository.slug}/pull/{pull.pullid}/diff?src=pr&el=tree#diff-ZmlsZV8xLmdv) | `62.50% <0.00%> (+12.50%)` | :arrow_up: |",
            f'',
            f'------',
            f'',
            f'[Continue to review full report at '
            f'Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).',
            f'> **Legend** - [Click here to learn '
            f'more](https://docs.codecov.io/docs/codecov-delta)',
            f'> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`',
            f'> Powered by '
            f'[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). '
            f'Last update '
            f'[b92edba...a06aef4](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). '
            f'Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).',
            f""
        ]
        li = 0
        for exp, res in zip(expected_result, result):
            li += 1
            print(li)
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_build_message_no_base_report(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison_without_base_report):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison_without_base_report
        pull = comparison.pull
        notifier = CommentNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'layout': "reach, diff, flags, files, footer"},
            notifier_site_settings=True,
            current_yaml={}
        )
        repository = comparison.head.commit.repository
        result = await notifier.build_message(comparison)
        expected_result = [
            f"# [Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=h1) Report",
            f"> :exclamation: No coverage uploaded for pull request base (`master@b92edba`). [Click here to learn what that means](https://docs.codecov.io/docs/error-reference#section-missing-base-commit).",
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
            f"| #unit | `100.00% <100.00%> (?)` | `0.00 <0.00> (?)` | |",
            f"",
            f"",
            f'------',
            f'',
            f'[Continue to review full report at '
            f'Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=continue).',
            f'> **Legend** - [Click here to learn '
            f'more](https://docs.codecov.io/docs/codecov-delta)',
            f'> `Δ = absolute <relative> (impact)`, `ø = not affected`, `? = missing data`',
            f'> Powered by '
            f'[Codecov](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=footer). '
            f'Last update '
            f'[b92edba...a06aef4](test.example.br/gh/{repository.slug}/pull/{pull.pullid}?src=pr&el=lastupdated). '
            f'Read the [comment docs](https://docs.codecov.io/docs/pull-request-comments).',
            f""
        ]
        for exp, res in zip(expected_result, result):
            assert exp == res
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_send_actual_notification_spammy(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'spammy'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': 9865}
        mock_repo_provider.post_comment.assert_called_with(98, 'message')
        assert not mock_repo_provider.edit_comment.called
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_new(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'new'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.delete_comment.return_value.set_result(True)
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': 9865}
        mock_repo_provider.post_comment.assert_called_with(98, 'message')
        assert not mock_repo_provider.edit_comment.called
        mock_repo_provider.delete_comment.assert_called_with(98, '12345')

    @pytest.mark.asyncio
    async def test_send_actual_notification_new_deleted_comment(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'new'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.delete_comment.return_value.set_exception(TorngitObjectNotFoundError('response', 'message'))
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': 9865}
        mock_repo_provider.post_comment.assert_called_with(98, 'message')
        assert not mock_repo_provider.edit_comment.called
        mock_repo_provider.delete_comment.assert_called_with(98, '12345')

    @pytest.mark.asyncio
    async def test_send_actual_notification_once_deleted_comment(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'once'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.edit_comment.return_value.set_exception(TorngitObjectNotFoundError('response', 'message'))
        result = await notifier.send_actual_notification(data)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == 'comment_deleted'
        assert result.data_sent == data
        assert result.data_received is None
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, '12345', 'message')
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_once_non_existing_comment(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'once'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': None,
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.edit_comment.return_value.set_exception(TorngitObjectNotFoundError('response', 'message'))
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': 9865}
        mock_repo_provider.post_comment.assert_called_with(98, 'message')
        assert not mock_repo_provider.delete_comment.called
        assert not mock_repo_provider.edit_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_once(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'once'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.edit_comment.return_value.set_result({'id': '49'})
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': '49'}
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, '12345', 'message')
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_default(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'default'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.edit_comment.return_value.set_result({'id': '49'})
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': '49'}
        assert not mock_repo_provider.post_comment.called
        mock_repo_provider.edit_comment.assert_called_with(98, '12345', 'message')
        assert not mock_repo_provider.delete_comment.called

    @pytest.mark.asyncio
    async def test_send_actual_notification_default_comment_not_found(self, dbsession, mock_configuration, mock_repo_provider, sample_comparison):
        notifier = CommentNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'layout': "reach, diff, flags, files, footer",
                'behavior': 'default'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        data = {
            'message': ['message'],
            'commentid': '12345',
            'pullid': 98
        }
        mock_repo_provider.post_comment.return_value.set_result({'id': 9865})
        mock_repo_provider.edit_comment.return_value.set_exception(TorngitObjectNotFoundError('response', 'message'))
        result = await notifier.send_actual_notification(data)
        assert result.notification_attempted
        assert result.notification_successful
        assert result.explanation is None
        assert result.data_sent == data
        assert result.data_received == {'id': 9865}
        mock_repo_provider.edit_comment.assert_called_with(98, '12345', 'message')
        mock_repo_provider.post_comment.assert_called_with(98, 'message')
        assert not mock_repo_provider.delete_comment.called
