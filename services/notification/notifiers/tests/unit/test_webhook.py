from decimal import Decimal

from database.tests.factories import CommitFactory, RepositoryFactory
from services.comparison.types import FullCommit
from services.notification.notifiers.webhook import WebhookNotifier
from services.repository import get_repo_provider_service


class TestWebhookNotifier(object):
    def test_build_commit_payload(
        self, dbsession, mock_configuration, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        repository = RepositoryFactory.create(
            owner__username="TestWebhookNotifier", name="test_build_payload"
        )
        dbsession.add(repository)
        dbsession.flush()
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        pull = sample_comparison.pull
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        notifier = WebhookNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(
                sample_comparison.head.commit.repository
            ),
        )
        repository = base_commit.repository
        comparison = sample_comparison
        result = notifier.build_commit_payload(comparison.head)
        expected_result = {
            "author": {
                "username": head_commit.author.username,
                "service_id": head_commit.author.service_id,
                "email": head_commit.author.email,
                "service": head_commit.author.service,
                "name": head_commit.author.name,
            },
            "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
            "timestamp": "2019-02-01T17:59:47",
            "totals": {
                "files": 2,
                "lines": 10,
                "hits": 6,
                "misses": 3,
                "partials": 1,
                "coverage": "60.00000",
                "branches": 1,
                "methods": 0,
                "messages": 0,
                "sessions": 1,
                "complexity": 10,
                "complexity_total": 2,
                "diff": 0,
            },
            "commitid": head_commit.commitid,
            "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
            "branch": "new_branch",
            "message": head_commit.message,
        }
        assert result["totals"] == expected_result["totals"]
        assert result == expected_result

    def test_build_commit_payload_gitlab(
        self, dbsession, mock_configuration, create_sample_comparison
    ):
        subgroup_namespace_path = "group/subgroup1/subsubgroup"
        username_in_db = subgroup_namespace_path.replace("/", ":")
        sample_comparison = create_sample_comparison(
            username=username_in_db, service="gitlab"
        )

        mock_configuration.params["setup"]["codecov_dashboard_url"] = "codecov.io"
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        pull = sample_comparison.pull
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        notifier = WebhookNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(
                sample_comparison.head.commit.repository
            ),
        )
        repository = base_commit.repository
        comparison = sample_comparison
        result = notifier.build_commit_payload(comparison.head)
        expected_result = {
            "author": {
                "username": head_commit.author.username,
                "service_id": head_commit.author.service_id,
                "email": head_commit.author.email,
                "service": head_commit.author.service,
                "name": head_commit.author.name,
            },
            "url": f"codecov.io/gl/{username_in_db}/{repository.name}/commit/{head_commit.commitid}",
            "timestamp": "2019-02-01T17:59:47",
            "totals": {
                "files": 2,
                "lines": 10,
                "hits": 6,
                "misses": 3,
                "partials": 1,
                "coverage": "60.00000",
                "branches": 1,
                "methods": 0,
                "messages": 0,
                "sessions": 1,
                "complexity": 10,
                "complexity_total": 2,
                "diff": 0,
            },
            "commitid": head_commit.commitid,
            "service_url": f"https://gitlab.com/{subgroup_namespace_path}/{repository.name}/commit/{head_commit.commitid}",
            "branch": "new_branch",
            "message": head_commit.message,
        }
        assert result == expected_result

    def test_build_commit_payload_no_author(
        self, dbsession, mock_configuration, sample_report
    ):
        repository = RepositoryFactory.create(
            owner__username="test_build_commit_payload_no_author",
            owner__service="github",
        )
        dbsession.add(repository)
        dbsession.flush()
        head_commit = CommitFactory.create(
            repository=repository, branch="new_branch", author=None
        )
        head_full_commit = FullCommit(commit=head_commit, report=sample_report)
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        dbsession.add(head_commit)
        dbsession.flush()
        notifier = WebhookNotifier(
            repository=repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(repository),
        )
        result = notifier.build_commit_payload(head_full_commit)
        expected_result = {
            "author": None,
            "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
            "timestamp": "2019-02-01T17:59:47",
            "totals": {
                "files": 2,
                "lines": 10,
                "hits": 6,
                "misses": 3,
                "partials": 1,
                "coverage": "60.00000",
                "branches": 1,
                "methods": 0,
                "messages": 0,
                "sessions": 1,
                "complexity": 10,
                "complexity_total": 2,
                "diff": 0,
            },
            "commitid": head_commit.commitid,
            "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
            "branch": "new_branch",
            "message": head_commit.message,
        }
        assert result == expected_result

    def test_build_payload(self, dbsession, mock_configuration, sample_comparison):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        repository = RepositoryFactory.create(
            owner__username="TestWebhookNotifier", name="test_build_payload"
        )
        dbsession.add(repository)
        dbsession.flush()
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        pull = sample_comparison.pull
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        notifier = WebhookNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(
                sample_comparison.head.commit.repository
            ),
        )
        repository = base_commit.repository
        comparison = sample_comparison
        result = notifier.build_payload(comparison)
        expected_result = {
            "repo": {
                "url": f"test.example.br/gh/{repository.slug}",
                "service_id": repository.service_id,
                "name": repository.name,
                "private": True,
            },
            "head": {
                "author": {
                    "username": head_commit.author.username,
                    "service_id": head_commit.author.service_id,
                    "email": head_commit.author.email,
                    "service": head_commit.author.service,
                    "name": head_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 10,
                    "hits": 6,
                    "misses": 3,
                    "partials": 1,
                    "coverage": "60.00000",
                    "branches": 1,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 10,
                    "complexity_total": 2,
                    "diff": 0,
                },
                "commitid": head_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
                "branch": "new_branch",
                "message": head_commit.message,
            },
            "base": {
                "author": {
                    "username": base_commit.author.username,
                    "service_id": base_commit.author.service_id,
                    "email": base_commit.author.email,
                    "service": base_commit.author.service,
                    "name": base_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{base_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 6,
                    "hits": 3,
                    "misses": 3,
                    "partials": 0,
                    "coverage": "50.00000",
                    "branches": 0,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 11,
                    "complexity_total": 20,
                    "diff": 0,
                },
                "commitid": base_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{base_commit.commitid}",
                "branch": None,
                "message": base_commit.message,
            },
            "compare": {
                "url": f"test.example.br/gh/{repository.slug}/pull/{pull.pullid}",
                "message": "increased",
                "coverage": Decimal("10.00"),
                "notation": "+",
            },
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": "github",
            },
            "pull": {
                "head": {"commit": head_commit.commitid, "branch": "master"},
                "number": str(pull.pullid),
                "base": {"commit": base_commit.commitid, "branch": "master"},
                "open": True,
                "id": pull.pullid,
                "merged": False,
            },
        }
        assert result["repo"] == expected_result["repo"]
        assert result["head"]["totals"] == expected_result["head"]["totals"]
        assert result["head"] == expected_result["head"]
        assert result["base"]["totals"] == expected_result["base"]["totals"]
        assert result["base"] == expected_result["base"]
        assert result["compare"] == expected_result["compare"]
        assert result["owner"] == expected_result["owner"]
        assert result["pull"] == expected_result["pull"]
        assert result == expected_result

    def test_build_payload_higher_precision(
        self, dbsession, mock_configuration, sample_comparison
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        repository = RepositoryFactory.create(
            owner__username="TestWebhookNotifier", name="test_build_payload"
        )
        dbsession.add(repository)
        dbsession.flush()
        base_commit = sample_comparison.project_coverage_base.commit
        head_commit = sample_comparison.head.commit
        pull = sample_comparison.pull
        dbsession.add(base_commit)
        dbsession.add(head_commit)
        dbsession.add(pull)
        dbsession.flush()
        notifier = WebhookNotifier(
            repository=sample_comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={"coverage": {"precision": 5, "round": "up"}},
            repository_service=get_repo_provider_service(
                sample_comparison.head.commit.repository
            ),
        )
        repository = base_commit.repository
        comparison = sample_comparison
        result = notifier.build_payload(comparison)
        expected_result = {
            "repo": {
                "url": f"test.example.br/gh/{repository.slug}",
                "service_id": repository.service_id,
                "name": repository.name,
                "private": True,
            },
            "head": {
                "author": {
                    "username": head_commit.author.username,
                    "service_id": head_commit.author.service_id,
                    "email": head_commit.author.email,
                    "service": head_commit.author.service,
                    "name": head_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 10,
                    "hits": 6,
                    "misses": 3,
                    "partials": 1,
                    "coverage": "60.00000",
                    "branches": 1,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 10,
                    "complexity_total": 2,
                    "diff": 0,
                },
                "commitid": head_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
                "branch": "new_branch",
                "message": head_commit.message,
            },
            "base": {
                "author": {
                    "username": base_commit.author.username,
                    "service_id": base_commit.author.service_id,
                    "email": base_commit.author.email,
                    "service": base_commit.author.service,
                    "name": base_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{base_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 6,
                    "hits": 3,
                    "misses": 3,
                    "partials": 0,
                    "coverage": "50.00000",
                    "branches": 0,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 11,
                    "complexity_total": 20,
                    "diff": 0,
                },
                "commitid": base_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{base_commit.commitid}",
                "branch": None,
                "message": base_commit.message,
            },
            "compare": {
                "url": f"test.example.br/gh/{repository.slug}/pull/{pull.pullid}",
                "message": "increased",
                "coverage": Decimal("10.00"),
                "notation": "+",
            },
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": "github",
            },
            "pull": {
                "head": {"commit": head_commit.commitid, "branch": "master"},
                "number": str(pull.pullid),
                "base": {"commit": base_commit.commitid, "branch": "master"},
                "open": True,
                "id": pull.pullid,
                "merged": False,
            },
        }

        assert result["repo"] == expected_result["repo"]
        assert result["head"] == expected_result["head"]
        assert result["base"]["totals"] == expected_result["base"]["totals"]
        assert result["base"] == expected_result["base"]
        assert result["compare"] == expected_result["compare"]
        assert result["owner"] == expected_result["owner"]
        assert result["pull"] == expected_result["pull"]
        assert result == expected_result

    def test_build_payload_without_pull(
        self, sample_comparison_without_pull, mock_configuration
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_pull
        commit = sample_comparison_without_pull.head.commit
        base_commit = comparison.project_coverage_base.commit
        head_commit = comparison.head.commit
        repository = commit.repository
        notifier = WebhookNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(
                comparison.head.commit.repository
            ),
        )
        result = notifier.build_payload(comparison)
        expected_result = {
            "repo": {
                "url": f"test.example.br/gh/{repository.slug}",
                "service_id": repository.service_id,
                "name": repository.name,
                "private": True,
            },
            "head": {
                "author": {
                    "username": head_commit.author.username,
                    "service_id": head_commit.author.service_id,
                    "email": head_commit.author.email,
                    "service": head_commit.author.service,
                    "name": head_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 10,
                    "hits": 6,
                    "misses": 3,
                    "partials": 1,
                    "coverage": "60.00000",
                    "branches": 1,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 10,
                    "complexity_total": 2,
                    "diff": 0,
                },
                "commitid": head_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
                "branch": "new_branch",
                "message": head_commit.message,
            },
            "base": {
                "author": {
                    "username": base_commit.author.username,
                    "service_id": base_commit.author.service_id,
                    "email": base_commit.author.email,
                    "service": base_commit.author.service,
                    "name": base_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{base_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 6,
                    "hits": 3,
                    "misses": 3,
                    "partials": 0,
                    "coverage": "50.00000",
                    "branches": 0,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 11,
                    "complexity_total": 20,
                    "diff": 0,
                },
                "commitid": base_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{base_commit.commitid}",
                "branch": None,
                "message": base_commit.message,
            },
            "compare": {
                "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
                "message": "increased",
                "coverage": Decimal("10.00"),
                "notation": "+",
            },
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": "github",
            },
            "pull": None,
        }

        assert result["repo"] == expected_result["repo"]
        assert result["head"] == expected_result["head"]
        assert result["base"]["totals"] == expected_result["base"]["totals"]
        assert result["base"] == expected_result["base"]
        assert result["compare"] == expected_result["compare"]
        assert result["owner"] == expected_result["owner"]
        assert result["pull"] == expected_result["pull"]
        assert result == expected_result

    def test_build_payload_without_base_report(
        self,
        sample_comparison_without_base_report,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_report
        commit = comparison.head.commit
        repository = commit.repository
        notifier = WebhookNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(
                comparison.head.commit.repository
            ),
        )
        result = notifier.build_payload(comparison)
        head_commit = comparison.head.commit
        base_commit = comparison.project_coverage_base.commit
        pull = comparison.pull
        expected_result = {
            "repo": {
                "url": f"test.example.br/gh/{repository.slug}",
                "service_id": repository.service_id,
                "name": repository.name,
                "private": True,
            },
            "head": {
                "author": {
                    "username": head_commit.author.username,
                    "service_id": head_commit.author.service_id,
                    "email": head_commit.author.email,
                    "service": head_commit.author.service,
                    "name": head_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 10,
                    "hits": 6,
                    "misses": 3,
                    "partials": 1,
                    "coverage": "60.00000",
                    "branches": 1,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 10,
                    "complexity_total": 2,
                    "diff": 0,
                },
                "commitid": head_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
                "branch": "new_branch",
                "message": head_commit.message,
            },
            "base": {
                "author": {
                    "username": base_commit.author.username,
                    "service_id": base_commit.author.service_id,
                    "email": base_commit.author.email,
                    "service": base_commit.author.service,
                    "name": base_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{base_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": None,
                "commitid": base_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{base_commit.commitid}",
                "branch": None,
                "message": base_commit.message,
            },
            "compare": {
                "url": None,
                "message": "unknown",
                "coverage": None,
                "notation": "",
            },
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": "github",
            },
            "pull": {
                "head": {"commit": head_commit.commitid, "branch": "master"},
                "number": str(pull.pullid),
                "base": {"commit": base_commit.commitid, "branch": "master"},
                "open": True,
                "id": pull.pullid,
                "merged": False,
            },
        }

        assert result["repo"] == expected_result["repo"]
        assert result["head"] == expected_result["head"]
        assert result["base"]["totals"] == expected_result["base"]["totals"]
        assert result["base"] == expected_result["base"]
        assert result["compare"] == expected_result["compare"]
        assert result["owner"] == expected_result["owner"]
        assert result["pull"] == expected_result["pull"]
        assert result == expected_result

    def test_build_payload_without_base(
        self,
        sample_comparison_without_base_with_pull,
        mock_configuration,
    ):
        mock_configuration.params["setup"]["codecov_dashboard_url"] = "test.example.br"
        comparison = sample_comparison_without_base_with_pull
        commit = comparison.head.commit
        repository = commit.repository
        notifier = WebhookNotifier(
            repository=comparison.head.commit.repository,
            title="title",
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={},
            repository_service=get_repo_provider_service(
                comparison.head.commit.repository
            ),
        )
        result = notifier.build_payload(comparison)
        head_commit = comparison.head.commit
        pull = comparison.pull
        expected_result = {
            "repo": {
                "url": f"test.example.br/gh/{repository.slug}",
                "service_id": repository.service_id,
                "name": repository.name,
                "private": True,
            },
            "head": {
                "author": {
                    "username": head_commit.author.username,
                    "service_id": head_commit.author.service_id,
                    "email": head_commit.author.email,
                    "service": head_commit.author.service,
                    "name": head_commit.author.name,
                },
                "url": f"test.example.br/gh/{repository.slug}/commit/{head_commit.commitid}",
                "timestamp": "2019-02-01T17:59:47",
                "totals": {
                    "files": 2,
                    "lines": 10,
                    "hits": 6,
                    "misses": 3,
                    "partials": 1,
                    "coverage": "60.00000",
                    "branches": 1,
                    "methods": 0,
                    "messages": 0,
                    "sessions": 1,
                    "complexity": 10,
                    "complexity_total": 2,
                    "diff": 0,
                },
                "commitid": head_commit.commitid,
                "service_url": f"https://github.com/{repository.slug}/commit/{head_commit.commitid}",
                "branch": "new_branch",
                "message": head_commit.message,
            },
            "base": None,
            "compare": {
                "url": None,
                "message": "unknown",
                "coverage": None,
                "notation": "",
            },
            "owner": {
                "username": repository.owner.username,
                "service_id": repository.owner.service_id,
                "service": "github",
            },
            "pull": {
                "head": {"commit": head_commit.commitid, "branch": "master"},
                "number": str(pull.pullid),
                "base": {"commit": "base_commitid", "branch": "master"},
                "open": True,
                "id": pull.pullid,
                "merged": False,
            },
        }

        assert result["repo"] == expected_result["repo"]
        assert result["head"] == expected_result["head"]
        assert result["base"] == expected_result["base"]
        assert result["compare"] == expected_result["compare"]
        assert result["owner"] == expected_result["owner"]
        assert result["pull"] == expected_result["pull"]
        assert result == expected_result
