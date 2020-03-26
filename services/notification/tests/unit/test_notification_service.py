from services.notification import NotificationService
from database.tests.factories import RepositoryFactory


class TestNotificationService(object):
    def test_get_notifiers_instances_only_third_party(
        self, dbsession, mock_configuration
    ):
        mock_configuration.params["services"] = {
            "notifications": {"slack": ["slack.com"]}
        }
        repository = RepositoryFactory.create(
            owner__unencrypted_oauth_token="testlln8sdeec57lz83oe3l8y9qq4lhqat2f1kzm",
            owner__username="ThiagoCodecov",
            yaml={"codecov": {"max_report_age": "1y ago"}},
            name="example-python",
        )
        dbsession.add(repository)
        dbsession.flush()
        current_yaml = {
            "coverage": {"notify": {"slack": {"default": {"field": "1y ago"}}}}
        }
        service = NotificationService(repository, current_yaml)
        instances = list(service.get_notifiers_instances())
        assert len(instances) == 1
        instance = instances[0]
        assert instance.repository == repository
        assert instance.title == "default"
        assert instance.notifier_yaml_settings == {"field": "1y ago"}
        assert instance.site_settings == ["slack.com"]
        assert instance.current_yaml == current_yaml
