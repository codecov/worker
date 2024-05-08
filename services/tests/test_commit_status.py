from services.commit_status import RepositoryCIFilter, _ci_providers


class TestCommitStatus(object):
    def test_ci_providers_no_config(self, mock_configuration):
        assert _ci_providers() == []

    def test_ci_providers_config_list(self, mock_configuration):
        mock_configuration.params["services"]["ci_providers"] = [
            "ser_1",
            "la_3",
            "something_4",
        ]
        assert _ci_providers() == ["ser_1", "la_3", "something_4"]

    def test_ci_providers_config_string(self, mock_configuration):
        mock_configuration.params["services"]["ci_providers"] = (
            "ser_1, la_3, something_4"
        )
        assert sorted(_ci_providers()) == sorted(["ser_1", "la_3", "something_4"])


class TestRepositoryCIFilter(object):
    def test_filter(self):
        service = RepositoryCIFilter(
            {"codecov": {"ci": ["simple", "!excluded", "another", "!reject"]}}
        )
        assert service._filter({"url": "https://www.example.com", "context": "simple"})
        assert service._filter({"url": "https://www.another.simple", "context": "ok"})
        assert service._filter(
            {"url": "http://www.another.simple", "context": "reject"}
        )
        assert not service._filter(
            {"url": "http://www.excluded.simple", "context": "reject"}
        )
        assert not service._filter(
            {"url": "http://www.another.reject", "context": "simple"}
        )
        assert not service._filter(
            {"url": "http://www.example.com", "context": "nothing"}
        )
        assert not service._filter(
            {"url": "http://www.example.com", "context": "excluded"}
        )
        assert not service._filter(
            {"url": "http://reject.example.com", "context": "ok"}
        )
        assert not service._filter({"url": "http://www.reject.com", "context": "ok"})
        assert not service._filter(
            {"url": "http://www.reject.com", "context": "simple"}
        )
        assert not service._filter(
            {"url": "http://www.ok.com", "context": "simple/reject"}
        )
        assert service._filter({"url": "http://www.ok.com", "context": "jenkins build"})

    def test_filter_jenkins_excluded(self):
        service = RepositoryCIFilter(
            {
                "codecov": {
                    "ci": ["simple", "!excluded", "!jenkins", "another", "!reject"]
                }
            }
        )
        assert not service._filter(
            {"url": "http://www.ok.com", "context": "jenkins build"}
        )
