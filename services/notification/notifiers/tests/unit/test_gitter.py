from decimal import Decimal

from services.notification.notifiers.gitter import GitterNotifier
from services.repository import get_repo_provider_service


def test_build_payload_without_special_config(
    dbsession, mock_configuration, sample_comparison
):
    mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
    comparison = sample_comparison
    notifier = GitterNotifier(
        repository=sample_comparison.head.commit.repository,
        title="title",
        notifier_yaml_settings={},
        notifier_site_settings=True,
        current_yaml={},
        repository_service=get_repo_provider_service(
            sample_comparison.head.commit.repository
        ),
    )
    result = notifier.build_payload(comparison)
    commit = comparison.head.commit
    repository = commit.repository
    text = f"Coverage *increased* +10.00% on `new_branch` is `60.00000%` via test.example.br/gh/{repository.slug}/commit/{commit.commitid}"
    expected_result = {
        "message": text,
        "branch": "new_branch",
        "pr": comparison.pull.pullid,
        "commit": commit.commitid,
        "commit_short": commit.commitid[:7],
        "text": "increased",
        "commit_url": f"https://github.com/{repository.slug}/commit/{commit.commitid}",
        "codecov_url": f"test.example.br/gh/{repository.slug}/commit/{commit.commitid}",
        "coverage": "60.00000",
        "coverage_change": Decimal("10.00"),
    }
    assert result["message"] == expected_result["message"]
    assert result == expected_result
