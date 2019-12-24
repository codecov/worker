import pytest
from asyncio import Future

from services.notification.notifiers.status import ProjectStatusNotifier, PatchStatusNotifier, ChangesStatusNotifier
from torngit.status import Status


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
                            'header': ['9', '7', '9', '8'],
                            'lines': [
                                ' Overview',
                                ' --------',
                                ' ',
                                '-Main website: `Codecov <https://codecov.io/>`_.',
                                '+',
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
        head_commit = sample_comparison.head.commit
        expected_result = {
            'message': f'60.00000% (+10.00%) compared to {base_commit.commitid[:7]}',
            'state': 'success',
            'url': f'test.example.br/gh/{head_commit.repository.slug}/compare/{base_commit.commitid}...{head_commit.commitid}'
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
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            'message': '60.00% (target 57.00%',
            'state': 'success',
            'url': f'test.example.br/gh/{head_commit.repository.slug}/compare/{base_commit.commitid}...{head_commit.commitid}'
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
            'url': f'test.example.br/gh/{head_commit.repository.slug}/compare/{base_commit.commitid}...{head_commit.commitid}'
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
        expected_result = {
            'notification_result': {
                'message': f'60.00000% (+10.00%) compared to {base_commit.commitid[:7]}',
                'response': {'id': 'some_id'},
                'state': 'success',
                'title': 'codecov/project/title'
            },
            'notified': True,
            'success': True
        }
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
        base_commit = sample_comparison.base.commit
        head_commit = sample_comparison.head.commit
        expected_result = {
            'message': f'Coverage not affected when comparing {base_commit.commitid[:7]}...{head_commit.commitid[:7]}',
            'state': 'success'
        }
        result = await notifier.build_payload(sample_comparison)
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
            'message': 'No unexpected coverage changes found.',
            'state': 'success'
        }
        result = await notifier.build_payload(sample_comparison)
        assert expected_result == result
