import httpx

from database.tests.factories import RepositoryFactory
from services.notification.notifiers.generics import (
    RequestsYamlBasedNotifier,
    StandardNotifier,
)


class SampleNotifierForTest(StandardNotifier):
    def build_payload(self, comparison):
        return {"commitid": comparison.head.commit.commitid}

    def send_actual_notification(self, data):
        return {
            "notification_attempted": True,
            "notification_successful": True,
            "explanation": None,
        }


class TestStandardkNotifier(object):
    def test_is_enabled_without_site_settings(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username="test_is_enabled_without_site_settings"
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=False,
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.is_enabled()

    def test_is_enabled_with_site_settings_no_special_config(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username="test_is_enabled_without_site_settings"
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={"url": "https://example.com/myexample"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert notifier.is_enabled()

    def test_is_enabled_with_site_settings_no_url(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username="test_is_enabled_without_site_settings"
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={"field_1": "something"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.is_enabled()

    def test_is_enabled_with_site_settings_whitelisted_url(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username="test_is_enabled_without_site_settings"
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={"url": "https://example.com/myexample"},
            notifier_site_settings=["example.com"],
            current_yaml={},
            repository_service=None,
        )
        assert notifier.is_enabled()

    def test_is_enabled_with_site_settings_not_whitelisted_url(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username="test_is_enabled_without_site_settings"
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={"url": "https://example.com/myexample"},
            notifier_site_settings=["badexample.com"],
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.is_enabled()

    def test_should_notify_comparison(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"url": "https://example.com/myexample"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_bad_branch(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "branches": ["test-.*"],
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_good_branch(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "branches": ["new_.*"],
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_not_above_threshold(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 80.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_no_base(
        self, sample_comparison_without_base_report
    ):
        notifier = StandardNotifier(
            repository=sample_comparison_without_base_report.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 80.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.should_notify_comparison(
            sample_comparison_without_base_report
        )

    def test_should_notify_comparison_is_above_threshold(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 8.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_is_above_threshold_no_coverage(
        self, sample_comparison
    ):
        actual_comparison = sample_comparison.get_filtered_comparison(
            path_patterns=[".*txt"], flags=None
        )
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 8.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        assert not notifier.should_notify_comparison(actual_comparison)

    def test_notify(self, sample_comparison):
        notifier = SampleNotifierForTest(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 8.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        res = notifier.notify(sample_comparison)
        assert res.notification_attempted
        assert res.notification_successful
        assert res.explanation is None
        assert res.data_sent == {"commitid": sample_comparison.head.commit.commitid}
        assert res.data_received is None

    def test_notify_should_not_notify(self, sample_comparison, mocker):
        notifier = SampleNotifierForTest(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 8.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        mocker.patch.object(
            SampleNotifierForTest, "should_notify_comparison", return_value=False
        )
        res = notifier.notify(sample_comparison)
        assert not res.notification_attempted
        assert res.notification_successful is None
        assert res.explanation == "Did not fit criteria"
        assert res.data_sent is None
        assert res.data_received is None


class TestRequestsYamlBasedNotifier(object):
    def test_send_notification_exception(self, mocker, sample_comparison):
        mocked_post = mocker.patch.object(httpx.Client, "post")
        mocked_post.side_effect = httpx.HTTPError("message")
        notifier = RequestsYamlBasedNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={
                "url": "https://example.com/myexample",
                "threshold": 8.0,
            },
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        data = {}
        res = notifier.send_actual_notification(data)
        assert res == {
            "notification_attempted": True,
            "notification_successful": False,
            "explanation": "connection_issue",
        }
