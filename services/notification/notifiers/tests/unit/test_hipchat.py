from services.notification.notifiers.hipchat import HipchatNotifier


class TestHipchatkNotifier(object):
    def test_build_payload_without_special_config(
        self, dbsession, mock_configuration, sample_comparison
    ):
        url = "test.example.br"
        mock_configuration.params["setup"]["codecov_dashboard_url"] = url
        comparison = sample_comparison
        notifier = HipchatNotifier(
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
        text = f'Coverage for <a href="test.example.br/gh/{repository.slug}/commit/{commit.commitid}">{repository.slug}</a> <strong>increased</strong> <code>+10.00%</code> on <code>new_branch</code> is <code>60.00000%</code> # via <a href="test.example.br/gh/{repository.slug}/commit/{commit.commitid}">{commit.commitid[:7]}</a>'
        expected_result = {
            "card": None,
            "color": "green",
            "from": "Codecov",
            "message": text,
            "message_format": "html",
            "notify": False,
        }
        assert result["message"] == expected_result["message"]
        assert result == expected_result

    def test_build_payload_without_base_report(
        self, sample_comparison, mock_configuration
    ):
        sample_comparison.project_coverage_base.report = None
        url = "test.example.br"
        mock_configuration.params["setup"]["codecov_dashboard_url"] = url
        comparison = sample_comparison
        notifier = HipchatNotifier(
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
        text = f'Coverage for <a href="test.example.br/gh/{repository.slug}/commit/{commit.commitid}">{repository.slug}</a> on <code>new_branch</code> is <code>60.00000%</code> # via <a href="test.example.br/gh/{repository.slug}/commit/{commit.commitid}">{commit.commitid[:7]}</a>'
        expected_result = {
            "card": None,
            "color": "gray",
            "from": "Codecov",
            "message": text,
            "message_format": "html",
            "notify": False,
        }
        assert result["message"] == expected_result["message"]
        assert result == expected_result

    def test_build_payload_with_card(self, sample_comparison, mock_configuration):
        url = "test.example.br"
        mock_configuration.params["setup"]["codecov_dashboard_url"] = url
        notifier = HipchatNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={"card": True},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=None,
        )
        result = notifier.build_payload(sample_comparison)
        commit = sample_comparison.head.commit
        repository = commit.repository
        text = f'Coverage for <a href="test.example.br/gh/{repository.slug}/commit/{commit.commitid}">{repository.slug}</a> <strong>increased</strong> <code>+10.00%</code> on <code>new_branch</code> is <code>60.00000%</code> # via <a href="test.example.br/gh/{repository.slug}/commit/{commit.commitid}">{commit.commitid[:7]}</a>'
        expected_result = {
            "card": {
                "attributes": [
                    {
                        "label": "Author",
                        "value": {
                            "label": commit.author.username,
                            "url": f"test.example.br/gh/{repository.slug}/commit/{commit.commitid}",
                        },
                    },
                    {
                        "label": "Commit",
                        "value": {
                            "label": commit.commitid[:7],
                            "url": f"test.example.br/gh/{repository.slug}/commit/{commit.commitid}",
                        },
                    },
                    {
                        "label": "Compare",
                        "value": {"label": "+10.00%", "style": "lozenge-success"},
                    },
                ],
                "description": {
                    "format": "html",
                    "value": f"Coverage for {repository.slug} on new_branch is now 60.00%",
                },
                "format": "compact",
                "icon": {
                    "url": f"test.example.br/gh/{repository.slug}/commit/{commit.commitid}/graphs/sunburst.svg?size=100"
                },
                "id": commit.commitid,
                "style": "application",
                "title": f"Codecov ⋅ {repository.slug} on new_branch",
                "url": f"test.example.br/gh/{repository.slug}/commit/{commit.commitid}",
            },
            "color": "green",
            "from": "Codecov",
            "message": text,
            "message_format": "html",
            "notify": False,
        }
        assert result["message"] == expected_result["message"]
        assert result["card"] == expected_result["card"]
        assert result == expected_result
