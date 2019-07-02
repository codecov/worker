import pytest

from tasks.upload import UploadTask
from database.tests.factories import CommitFactory
from services.archive import ArchiveService


class TestUploadTask(object):

    @pytest.mark.asyncio
    async def test_task_call(self, mocker, test_configuration, dbsession, codecov_vcr):
        mocked_lock = mocker.patch.object(UploadTask, 'acquire_lock')
        mocked_lock.return_value = True
        mocker.patch.object(UploadTask, 'release_lock')
        mocked_1 = mocker.patch.object(ArchiveService, 'read_chunks')
        mocked_1.return_value = None
        mocked_2 = mocker.patch.object(UploadTask, 'lists_of_arguments')
        url = 'v4/raw/2019-05-22/C3C4715CA57C910D11D5EB899FC86A7E/4c4e4654ac25037ae869caeb3619d485970b6304/a84d445c-9c1e-434f-8275-f18f1f320f81.txt'
        mocked_2.return_value = [
            {
                'url': url
            }
        ]
        mocked_3 = mocker.patch.object(UploadTask, 'app')
        mocked_3.send_task.return_value = True

        mocked_invalidate_caches = mocker.patch.object(UploadTask, 'invalidate_caches')
        mocked_invalidate_caches.return_value = True

        commit = CommitFactory.create(
            message='',
            commitid='abf6d4df662c47e32460020ab14abf9303581429',
            repository__owner__unencrypted_oauth_token='testp7cdou4qu77hzz6ghl0dsvrj2rzmdt0btoru',
            repository__owner__username='ThiagoCodecov',
            repository__yaml={'codecov': {'max_report_age': '1y ago'}},  # Sorry, this is a timebomb now
            repository__repoid=2,
        )
        dbsession.add(commit)
        dbsession.flush()
        result = await UploadTask().run_async(dbsession, commit.repoid, commit.commitid)
        expected_result = {
            'files': {
                'awesome/__init__.py': [
                    0,
                    [0, 14, 10, 4, 0, '71.42857', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 14, 10, 4, 0, '71.42857', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    [
                        0, 4, 4, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0
                    ]
                ],
                'tests/__init__.py': [
                    1,
                    [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    None
                ],
                'tests/test_sample.py': [
                    2,
                    [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0],
                    [
                        [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0]
                    ],
                    None
                ]
            },
            'sessions': {
                '0': {
                    'N': None,
                    'a': url,
                    'c': None,
                    'e': None,
                    'f': None,
                    'j': None,
                    'n': None,
                    'p': None,
                    't': [3, 24, 19, 5, 0, '79.16667', 0, 0, 0, 0, 0, 0, 0],
                    'u': None
                }
            }
        }

        assert expected_result['files']['awesome/__init__.py'] == result['files']['awesome/__init__.py']
        assert expected_result['files'] == result['files']
        del result['sessions']['0']['d']  # This is not deterministic
        assert expected_result['sessions'] == result['sessions']
        assert commit.message == 'dsidsahdsahdsa'
        mocked_1.assert_called_with(commit.commitid)
        mocked_2.assert_called_with(mocker.ANY, 'testuploads/%s/%s' % (commit.repoid, commit.commitid))
        mocked_3.send_task.assert_called_with(
            'app.tasks.notify.Notify',
            args=None,
            kwargs={'repoid': commit.repository.repoid, 'commitid': commit.commitid}
        )
        mocked_invalidate_caches.assert_called_with(mocker.ANY, commit)
