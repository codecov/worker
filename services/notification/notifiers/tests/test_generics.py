from services.notification.notifiers.generics import StandardNotifier
from database.tests.factories import RepositoryFactory


class SampleNotifierForTest(StandardNotifier):

    def build_payload(self, comparison):
        return {
            'commitid': comparison.head.commit.commitid
        }

    def send_actual_notification(self, data):
        return {
            'notification_attempted': True,
            'notification_successful': True,
            'explanation': None
        }


class TestStandardkNotifier(object):

    def test_is_enabled_without_site_settings(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username='test_is_enabled_without_site_settings',
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=False,
            current_yaml={}
        )
        assert not notifier.is_enabled()

    def test_is_enabled_with_site_settings_no_special_config(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username='test_is_enabled_without_site_settings',
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title='title',
            notifier_yaml_settings={'url': 'https://example.com/myexample'},
            notifier_site_settings=True,
            current_yaml={}
        )
        assert notifier.is_enabled()

    def test_is_enabled_with_site_settings_no_url(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username='test_is_enabled_without_site_settings',
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title='title',
            notifier_yaml_settings={'field_1': 'something'},
            notifier_site_settings=True,
            current_yaml={}
        )
        assert not notifier.is_enabled()

    def test_is_enabled_with_site_settings_whitelisted_url(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username='test_is_enabled_without_site_settings',
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title='title',
            notifier_yaml_settings={'url': 'https://example.com/myexample'},
            notifier_site_settings=['example.com'],
            current_yaml={}
        )
        assert notifier.is_enabled()

    def test_is_enabled_with_site_settings_not_whitelisted_url(self, dbsession):
        repository = RepositoryFactory.create(
            owner__username='test_is_enabled_without_site_settings',
        )
        dbsession.add(repository)
        dbsession.flush()
        notifier = StandardNotifier(
            repository=repository,
            title='title',
            notifier_yaml_settings={'url': 'https://example.com/myexample'},
            notifier_site_settings=['badexample.com'],
            current_yaml={}
        )
        assert not notifier.is_enabled()

    def test_should_notify_comparison(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'url': 'https://example.com/myexample'
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        assert notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_bad_branch(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'url': 'https://example.com/myexample',
                'branches': ['test-.*']
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        assert not notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_good_branch(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'url': 'https://example.com/myexample',
                'branches': ['new_.*']
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        assert notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_not_above_threshold(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'url': 'https://example.com/myexample',
                'threshold': 80.0
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        assert not notifier.should_notify_comparison(sample_comparison)

    def test_should_notify_comparison_is_above_threshold(self, sample_comparison):
        notifier = StandardNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'url': 'https://example.com/myexample',
                'threshold': 8.0
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        assert notifier.should_notify_comparison(sample_comparison)

    def test_notify(self, sample_comparison):
        notifier = SampleNotifierForTest(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={
                'url': 'https://example.com/myexample',
                'threshold': 8.0
            },
            notifier_site_settings=True,
            current_yaml={}
        )
        assert notifier.notify(sample_comparison)
