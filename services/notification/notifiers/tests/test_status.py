import pytest
from asyncio import Future

from covreports.resources import ReportLine, ReportFile, Report
from torngit.exceptions import TorngitClientError


from services.notification.notifiers.status import (
    ProjectStatusNotifier, PatchStatusNotifier, ChangesStatusNotifier
)
from services.notification.notifiers.status.base import StatusNotifier
from services.notification.notifiers.base import NotificationResult
from torngit.status import Status


@pytest.fixture
def multiple_diff_changes():
    return {
        'files': {
            'modified.py': {
                'before': None,
                'segments': [
                    {
                        'header': [
                            '20', '8', '20', '8'
                        ],
                        'lines': [
                            '     return k * k',
                            ' ',
                            ' ',
                            '-def k(l):',
                            '-    return 2 * l',
                            '+def k(var):',
                            '+    return 2 * var',
                            ' ',
                            ' ',
                            ' def sample_function():'
                        ]
                    }
                ],
                'stats': {
                    'added': 2, 'removed': 2
                },
                'type': 'modified'
            },
            'renamed.py': {
                'before': 'old_renamed.py',
                'segments': [],
                'stats': {'added': 0, 'removed': 0},
                'type': 'modified'
            },
            'renamed_with_changes.py': {
                'before': 'old_renamed_with_changes.py',
                'segments': [],
                'stats': {'added': 0, 'removed': 0},
                'type': 'modified'
            },
            'added.py': {
                'before': None,
                'segments': [
                    {
                        'header': ['0', '0', '1', ''],
                        'lines': [
                            '+This is an explanation'
                        ]
                    }
                ],
                'stats': {'added': 1, 'removed': 0},
                'type': 'new'
            },
            'deleted.py': {
                'before': 'tests/test_sample.py',
                'stats': {'added': 0, 'removed': 0},
                'type': 'deleted'
            }
        }
    }


@pytest.fixture
def comparison_with_multiple_changes(sample_comparison):
    first_report = Report()
    second_report = Report()
    # DELETED FILE
    first_deleted_file = ReportFile('deleted.py')
    first_deleted_file.append(10, ReportLine(coverage=1))
    first_deleted_file.append(12, ReportLine(coverage=0))
    first_report.append(first_deleted_file)
    # ADDED FILE
    second_added_file = ReportFile('added.py')
    second_added_file.append(99, ReportLine(coverage=1))
    second_added_file.append(101, ReportLine(coverage=0))
    second_report.append(second_added_file)
    # MODIFIED FILE
    first_modified_file = ReportFile('modified.py')
    first_modified_file.append(17, ReportLine(coverage=1))
    first_modified_file.append(18, ReportLine(coverage=1))
    first_modified_file.append(19, ReportLine(coverage=1))
    first_modified_file.append(20, ReportLine(coverage=0))
    first_modified_file.append(21, ReportLine(coverage=1))
    first_modified_file.append(22, ReportLine(coverage=1))
    first_modified_file.append(23, ReportLine(coverage=1))
    first_modified_file.append(24, ReportLine(coverage=1))
    first_report.append(first_modified_file)
    second_modified_file = ReportFile('modified.py')
    second_modified_file.append(18, ReportLine(coverage=1))
    second_modified_file.append(19, ReportLine(coverage=0))
    second_modified_file.append(20, ReportLine(coverage=0))
    second_modified_file.append(21, ReportLine(coverage=1))
    second_modified_file.append(22, ReportLine(coverage=0))
    second_modified_file.append(23, ReportLine(coverage=0))
    second_modified_file.append(24, ReportLine(coverage=1))
    second_report.append(second_modified_file)
    # RENAMED WITHOUT CHANGES
    first_renamed_without_changes_file = ReportFile('old_renamed.py')
    first_renamed_without_changes_file.append(1, ReportLine(coverage=1))
    first_renamed_without_changes_file.append(2, ReportLine(coverage=1))
    first_renamed_without_changes_file.append(3, ReportLine(coverage=0))
    first_renamed_without_changes_file.append(4, ReportLine(coverage=1))
    first_renamed_without_changes_file.append(5, ReportLine(coverage=0))
    first_report.append(first_renamed_without_changes_file)
    second_renamed_without_changes_file = ReportFile('renamed.py')
    second_renamed_without_changes_file.append(1, ReportLine(coverage=1))
    second_renamed_without_changes_file.append(2, ReportLine(coverage=1))
    second_renamed_without_changes_file.append(3, ReportLine(coverage=0))
    second_renamed_without_changes_file.append(4, ReportLine(coverage=1))
    second_renamed_without_changes_file.append(5, ReportLine(coverage=0))
    second_report.append(second_renamed_without_changes_file)
    # RENAMED WITH COVERAGE CHANGES FILE
    first_renamed_file = ReportFile('old_renamed_with_changes.py')
    first_renamed_file.append(2, ReportLine(coverage=1))
    first_renamed_file.append(3, ReportLine(coverage=1))
    first_renamed_file.append(5, ReportLine(coverage=0))
    first_renamed_file.append(8, ReportLine(coverage=1))
    first_renamed_file.append(13, ReportLine(coverage=1))
    first_report.append(first_renamed_file)
    second_renamed_file = ReportFile('renamed_with_changes.py')
    second_renamed_file.append(5, ReportLine(coverage=1))
    second_renamed_file.append(8, ReportLine(coverage=0))
    second_renamed_file.append(13, ReportLine(coverage=1))
    second_renamed_file.append(21, ReportLine(coverage=1))
    second_renamed_file.append(34, ReportLine(coverage=0))
    second_report.append(second_renamed_file)
    # UNRELATED FILE
    first_unrelated_file = ReportFile('unrelated.py')
    first_unrelated_file.append(1, ReportLine(coverage=1))
    first_unrelated_file.append(2, ReportLine(coverage=1))
    first_unrelated_file.append(4, ReportLine(coverage=1))
    first_unrelated_file.append(16, ReportLine(coverage=0))
    first_unrelated_file.append(256, ReportLine(coverage=1))
    first_unrelated_file.append(65556, ReportLine(coverage=1))
    first_report.append(first_unrelated_file)
    second_unrelated_file = ReportFile('unrelated.py')
    second_unrelated_file.append(2, ReportLine(coverage=1))
    second_unrelated_file.append(4, ReportLine(coverage=0))
    second_unrelated_file.append(8, ReportLine(coverage=0))
    second_unrelated_file.append(16, ReportLine(coverage=1))
    second_unrelated_file.append(32, ReportLine(coverage=0))
    second_report.append(second_unrelated_file)
    sample_comparison.base.report = first_report
    sample_comparison.head.report = second_report
    return sample_comparison


@pytest.fixture
def mock_repo_provider(mock_repo_provider):
    result = Future()
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
    result.set_result(compare_result)
    mock_repo_provider.get_compare.return_value = result
    return mock_repo_provider


class TestBaseStatusNotifier(object):

    def test_can_we_set_this_status_no_pull(self, sample_comparison_without_pull):
        comparison = sample_comparison_without_pull
        only_pulls_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'only_pulls': True},
            notifier_site_settings=True,
            current_yaml={}
        )
        assert not only_pulls_notifier.can_we_set_this_status(comparison)
        wrong_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'only_pulls': False, 'branches': ['old.*']},
            notifier_site_settings=True,
            current_yaml={}
        )
        assert not wrong_branch_notifier.can_we_set_this_status(comparison)
        right_branch_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'only_pulls': False, 'branches': ['new.*']},
            notifier_site_settings=True,
            current_yaml={}
        )
        assert right_branch_notifier.can_we_set_this_status(comparison)
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        assert no_settings_notifier.can_we_set_this_status(comparison)

    @pytest.mark.asyncio
    async def test_notify_cannot_set_status(self, sample_comparison, mocker):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        mocker.patch.object(
            StatusNotifier, 'can_we_set_this_status', return_value=False
        )
        result = await no_settings_notifier.notify(comparison)
        assert not result.notification_attempted
        assert result.notification_successful is None
        assert result.explanation == 'not_fit_criteria'
        assert result.data_sent is None
        assert result.data_received is None

    @pytest.mark.asyncio
    async def test_send_notification(self, sample_comparison, mocker, mock_repo_provider):
        comparison = sample_comparison
        no_settings_notifier = StatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        no_settings_notifier.context = 'fake'
        mocked_status_already_exists = mocker.patch.object(
            StatusNotifier, 'status_already_exists', return_value=Future()
        )
        mocked_status_already_exists.return_value.set_result(False)
        mock_repo_provider.set_commit_status.return_value = Future()
        mock_repo_provider.set_commit_status.return_value.set_exception(
            TorngitClientError(403, 'response', 'message')
        )
        payload = {
            'message': 'something to say',
            'state': 'success',
            'url': 'url'
        }
        result = await no_settings_notifier.send_notification(comparison, payload)
        assert result.notification_attempted
        assert not result.notification_successful
        assert result.explanation == 'no_write_permission'
        expected_data_sent = {
            'message': 'something to say',
            'state': 'success',
            'title': 'codecov/fake/title'
        }
        assert result.data_sent == expected_data_sent
        assert result.data_received is None


class TestProjectStatusNotifier(object):

    @pytest.mark.asyncio
    async def test_build_payload(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        base_commit = sample_comparison.base.commit
        expected_result = {
            'message': f'60.00% (+10.00%) compared to {base_commit.commitid[:7]}',
            'state': 'success',
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'target': '57%'},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '60.00% (target 57.00%)',
            'state': 'success',
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto_not_string(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'target': 57.0},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '60.00% (target 57.00%)',
            'state': 'success',
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_base_report(self, sample_comparison_without_base_report, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison_without_base_report
        notifier = ProjectStatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        base_commit = comparison.base.commit
        head_commit = comparison.head.commit
        expected_result = {
            'message': 'No report found to compare against',
            'state': 'success',
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_notify_status_doesnt_exist(self, sample_comparison, mock_repo_provider, mock_configuration):
        statuses = Future()
        statuses.set_result(Status([]))
        mock_repo_provider.get_commit_statuses.return_value = statuses
        mock_repo_provider.set_commit_status.return_value = Future()
        mock_repo_provider.set_commit_status.return_value.set_result({'id': 'some_id'})
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = ProjectStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        base_commit = sample_comparison.base.commit
        expected_result = NotificationResult(
            notification_attempted=True,
            notification_successful=True,
            explanation=None,
            data_sent={
                'message': f'60.00% (+10.00%) compared to {base_commit.commitid[:7]}',
                'state': 'success',
                'title': 'codecov/project/title'
            },
            data_received={'id': 'some_id'}
        )
        result = await notifier.notify(sample_comparison)
        assert expected_result == result


class TestPatchStatusNotifier(object):

    @pytest.mark.asyncio
    async def test_build_payload(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '66.67% of diff hit (target 50.00%)',
            'state': 'success'
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_target_coverage_failure(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'target': '70%'},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '66.67% of diff hit (target 70.00%)',
            'state': 'failure'
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_not_auto_not_string(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'target': 57.0},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '66.67% of diff hit (target 57.00%)',
            'state': 'success',
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_target_coverage_failure_witinh_threshold(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        third_file = ReportFile('file_3.c')
        third_file.append(100, ReportLine(coverage=1, sessions=[[0, 1]]))
        third_file.append(101, ReportLine(coverage=1, sessions=[[0, 1]]))
        third_file.append(102, ReportLine(coverage=1, sessions=[[0, 1]]))
        third_file.append(103, ReportLine(coverage=1, sessions=[[0, 1]]))
        sample_comparison.base.report.append(third_file)
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={'threshold': '5'},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '66.67% of diff hit (within 5.00% threshold of 70.00%)',
            'state': 'success'
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_diff(self, sample_comparison, mock_repo_provider, mock_configuration):
        f = Future()
        mock_repo_provider.get_compare.return_value = f
        f.set_result({
            'diff': {
                'files': {
                    'file_1.go': {
                        'type': 'modified',
                        'before': None,
                        'segments': [
                            {
                                'header': ['15', '8', '15', '9'],
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
                        ],
                        'stats': {'added': 11, 'removed': 4}
                    }
                }
            }
        })
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = PatchStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            'message': f'Coverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}',
            'state': 'success'
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_no_diff_no_base_report(self, sample_comparison_without_base, mock_repo_provider, mock_configuration):
        f = Future()
        mock_repo_provider.get_compare.return_value = f
        f.set_result({
            'diff': {
                'files': {
                    'file_1.go': {
                        'type': 'modified',
                        'before': None,
                        'segments': [
                            {
                                'header': ['15', '8', '15', '9'],
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
                        ],
                        'stats': {'added': 11, 'removed': 4}
                    }
                }
            }
        })
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison_without_base
        notifier = PatchStatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': f'Coverage not affected',
            'state': 'success'
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_without_base_report(self, sample_comparison_without_base_report, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison_without_base_report
        notifier = PatchStatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': f'No report found to compare against',
            'state': 'success'
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_with_multiple_changes(self, comparison_with_multiple_changes, mock_repo_provider, mock_configuration, multiple_diff_changes):
        json_diff = multiple_diff_changes
        f = Future()
        mock_repo_provider.get_compare.return_value = f
        f.set_result({'diff': json_diff})

        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = PatchStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '50.00% of diff hit (target 76.92%)',
            'state': 'failure'
        }
        result = await notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result


class TestChangesStatusNotifier(object):

    @pytest.mark.asyncio
    async def test_build_payload(self, sample_comparison, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = ChangesStatusNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': 'No unexpected coverage changes found',
            'state': 'success'
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_with_multiple_changes(self, comparison_with_multiple_changes, mock_repo_provider, mock_configuration, multiple_diff_changes):
        json_diff = multiple_diff_changes
        f = Future()
        mock_repo_provider.get_compare.return_value = f
        f.set_result({'diff': json_diff})

        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        notifier = ChangesStatusNotifier(
            repository=comparison_with_multiple_changes.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': '3 files have unexpected coverage changes not visible in diff',
            'state': 'failure'
        }
        result = await notifier.build_payload(comparison_with_multiple_changes)
        assert expected_result == result

    @pytest.mark.asyncio
    async def test_build_payload_without_base_report(self, sample_comparison_without_base_report, mock_repo_provider, mock_configuration):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison_without_base_report
        notifier = ChangesStatusNotifier(
            repository=comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        expected_result = {
            'message': 'Unable to determine changes, no report found at pull request base',
            'state': 'success'
        }
        result = await notifier.build_payload(comparison)
        assert expected_result == result
