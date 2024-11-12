from services.notification.notifiers.slack import SlackNotifier


class TestSlackNotifier(object):
    def test_build_payload_without_attachments(
        self, dbsession, mock_configuration, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        notifier = SlackNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(comparison)
        commit = comparison.head.commit
        repository = commit.repository
        text = f"Coverage for <test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{repository.slug}> *increased* `<test.example.br/gh/{repository.slug}/pull/{comparison.pull.pullid}|+10.00%>` on `new_branch` is `60.00000%` via `<test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{commit.commitid[:7]}>`"
        expected_result = {
            "attachments": [],
            "author_link": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}",
            "author_name": "Codecov",
            "text": text,
        }
        print(result["text"])
        assert result == expected_result

    def test_build_payload_with_attachments(
        self, dbsession, mock_configuration, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        notifier = SlackNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"attachments": ["sunburst"]},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(comparison)
        commit = comparison.head.commit
        repository = commit.repository
        text = f"Coverage for <test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{repository.slug}> *increased* `<test.example.br/gh/{repository.slug}/pull/{comparison.pull.pullid}|+10.00%>` on `new_branch` is `60.00000%` via `<test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{commit.commitid[:7]}>`"
        expected_result = {
            "attachments": [
                {
                    "color": "good",
                    "fallback": "Commit sunburst attachment",
                    "image_url": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}/graphs/sunburst.svg?size=100",
                    "title": "Commit Sunburst",
                    "title_link": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}",
                }
            ],
            "author_link": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}",
            "author_name": "Codecov",
            "text": text,
        }
        assert result["attachments"][0] == expected_result["attachments"][0]
        assert result == expected_result

    def test_build_payload_with_message(
        self, dbsession, mock_configuration, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison
        notifier = SlackNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"message": "This is a sample"},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(comparison)
        commit = comparison.head.commit
        expected_result = {
            "attachments": [],
            "author_link": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}",
            "author_name": "Codecov",
            "text": "This is a sample",
        }
        print(result["text"])
        assert result == expected_result

    def test_build_payload_without_pull(
        self, sample_comparison_without_pull, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_pull
        commit = sample_comparison_without_pull.head.commit
        repository = commit.repository
        notifier = SlackNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(comparison)
        text = f"Coverage for <test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{repository.slug}> *increased* `<test.example.br/gh/{repository.slug}/commit/{commit.commitid}|+10.00%>` on `new_branch` is `60.00000%` via `<test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{commit.commitid[:7]}>`"
        expected_result = {
            "attachments": [],
            "author_link": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}",
            "author_name": "Codecov",
            "text": text,
        }
        assert result["text"] == expected_result["text"]
        assert result == expected_result

    def test_build_payload_without_base(
        self, sample_comparison_without_base_report, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        commit = comparison.head.commit
        repository = commit.repository
        notifier = SlackNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(comparison)
        text = f"Coverage for <test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{repository.slug}> on `new_branch` is `60.00000%` via `<test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{commit.commitid[:7]}>`"
        expected_result = {
            "attachments": [],
            "author_link": f"test.example.br/gh/{commit.repository.slug}/commit/{commit.commitid}",
            "author_name": "Codecov",
            "text": text,
        }
        assert result["text"] == expected_result["text"]
        assert result == expected_result
