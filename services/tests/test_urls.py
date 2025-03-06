from database.tests.factories import OwnerFactory, PullFactory, RepositoryFactory
from services.urls import append_tracking_params_to_urls, get_members_url, get_plan_url


def test_append_tracking_params_to_urls():
    message = [
        "[This link](https://stage.codecov.io/gh/test_repo/pull/pull123?src=pr&el=h1) should be changed",
        "And [this one](https://codecov.io/bb/test_repo/pull) too, plus also [this one](codecov.io)",
        "However, [this one](https://www.xkcd.com/) should not be changed since it does not link to Codecov",
        "(Also should not replace this parenthetical non-link reference to codecov.io)",
        "Also should recognize that these are two separate URLs: [banana](https://codecov.io/pokemon)and[banana](https://codecov.io/pokemon)",
    ]

    service = "github"
    notification_type = "comment"
    org_name = "Acme Corporation"

    expected_result = [
        "[This link](https://stage.codecov.io/gh/test_repo/pull/pull123?src=pr&el=h1&utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation) should be changed",
        "And [this one](https://codecov.io/bb/test_repo/pull?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation) too, plus also [this one](codecov.io?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation)",
        "However, [this one](https://www.xkcd.com/) should not be changed since it does not link to Codecov",
        "(Also should not replace this parenthetical non-link reference to codecov.io)",
        "Also should recognize that these are two separate URLs: [banana](https://codecov.io/pokemon?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation)and[banana](https://codecov.io/pokemon?utm_medium=referral&utm_source=github&utm_content=comment&utm_campaign=pr+comments&utm_term=Acme+Corporation)",
    ]
    result = [
        append_tracking_params_to_urls(
            m, service=service, notification_type=notification_type, org_name=org_name
        )
        for m in message
    ]

    assert result == expected_result


class TestURLs(object):
    def test_gitlab_url_username_swap(self, dbsession):
        base_for_member_url = "https://app.codecov.io/members/"
        base_for_plan_url = "https://app.codecov.io/plan/"

        github_org = OwnerFactory.create(
            service="github",
            username="gh",
        )
        dbsession.add(github_org)
        r = RepositoryFactory.create(owner=github_org)
        dbsession.add(r)
        gh_pull = PullFactory.create(repository=r)
        dbsession.add(gh_pull)
        dbsession.flush()
        member_url = get_members_url(gh_pull)
        assert member_url == base_for_member_url + "gh/gh"

        gitlab_root_org = OwnerFactory.create(service="gitlab", username="gl_root")
        dbsession.add(gitlab_root_org)
        r = RepositoryFactory.create(owner=gitlab_root_org)
        dbsession.add(r)
        gl_root_pull = PullFactory.create(repository=r)
        dbsession.add(gl_root_pull)
        dbsession.flush()
        plan_url = get_plan_url(gl_root_pull)
        assert plan_url == base_for_plan_url + "gl/gl_root"

        gitlab_mid_org = OwnerFactory.create(
            service="gitlab",
            username="gl_mid",
            parent_service_id=gitlab_root_org.service_id,
        )
        dbsession.add(gitlab_mid_org)
        r = RepositoryFactory.create(owner=gitlab_mid_org)
        dbsession.add(r)
        gl_mid_pull = PullFactory.create(repository=r)
        dbsession.add(gl_mid_pull)
        dbsession.flush()
        member_url = get_members_url(gl_mid_pull)
        assert member_url == base_for_member_url + "gl/gl_root"

        gitlab_sub_org = OwnerFactory.create(
            service="gitlab",
            username="gl_child",
            parent_service_id=gitlab_mid_org.service_id,
        )
        dbsession.add(gitlab_sub_org)
        r = RepositoryFactory.create(owner=gitlab_sub_org)
        dbsession.add(r)
        gl_child_pull = PullFactory.create(repository=r)
        dbsession.add(gl_child_pull)
        dbsession.flush()
        plan_url = get_plan_url(gl_child_pull)
        assert plan_url == base_for_plan_url + "gl/gl_root"
