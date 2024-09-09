import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import List
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

from shared.config import get_config

from database.models import Commit, Pull, Repository
from services.license import requires_license

services_short_dict = dict(
    github="gh",
    github_enterprise="ghe",
    bitbucket="bb",
    bitbucket_server="bbs",
    gitlab="gl",
    gitlab_enterprise="gle",
)

log = logging.getLogger(__name__)


class SiteUrls(Enum):
    commit_url = (
        "{base_url}/{service_short}/{username}/{project_name}/commit/{commit_sha}"
    )
    compare_url = "{base_url}/{service_short}/{username}/{project_name}/compare/{base_sha}...{head_sha}"
    repository_url = "{base_url}/{service_short}/{username}/{project_name}"
    graph_url = "{base_url}/{service_short}/{username}/{project_name}/commit/{commit_sha}/graphs/{graph_filename}"
    pull_url = "{base_url}/{service_short}/{username}/{project_name}/pull/{pull_id}"
    new_client_pull_url = "https://app.codecov.io/{service_short}/{username}/{project_name}/compare/{pull_id}"
    pull_graph_url = "{base_url}/{service_short}/{username}/{project_name}/pull/{pull_id}/graphs/{graph_filename}"
    org_acccount_url = "{dashboard_base_url}/account/{service_short}/{username}"
    members_url = "{dashboard_base_url}/members/{service_short}/{username}"
    members_url_self_hosted = "{dashboard_base_url}/account/{service_short}/{username}"
    plan_url = "{dashboard_base_url}/plan/{service_short}/{username}"
    test_analytics_url = "{dashboard_base_url}/{service_short}/{username}/{project_name}/tests/{branch_name}"

    def get_url(self, **kwargs) -> str:
        return self.value.format(**kwargs)


def get_base_url() -> str:
    return get_config("setup", "codecov_url")


def get_dashboard_base_url() -> str:
    configured_dashboard_url = get_config("setup", "codecov_dashboard_url")
    configured_base_url = get_base_url()
    # Enterprise users usually configure the base url not the dashboard one,
    # app.codecov.io is for cloud users so we want to prioritize the values correctly
    if requires_license():
        return configured_dashboard_url or configured_base_url
    else:
        return configured_dashboard_url or "https://app.codecov.io"


def get_commit_url(commit: Commit) -> str:
    return SiteUrls.commit_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(commit.repository.service),
        username=commit.repository.owner.username,
        project_name=commit.repository.name,
        commit_sha=commit.commitid,
    )


def get_commit_url_from_commit_sha(repository, commit_sha) -> str:
    return SiteUrls.commit_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
        project_name=repository.name,
        commit_sha=commit_sha,
    )


def get_graph_url(commit: Commit, graph_filename: str, **kwargs) -> str:
    url = SiteUrls.graph_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(commit.repository.service),
        username=commit.repository.owner.username,
        project_name=commit.repository.name,
        commit_sha=commit.commitid,
        graph_filename=graph_filename,
    )
    encoded_kwargs = urlencode(kwargs)
    return f"{url}?{encoded_kwargs}"


def get_compare_url(base_commit: Commit, head_commit: Commit) -> str:
    log.warning(
        "Compare links are deprecated.", extra=dict(head_commit=head_commit.commitid)
    )
    return SiteUrls.compare_url.get_url(
        base_url=get_base_url(),
        service_short=services_short_dict.get(head_commit.repository.service),
        username=head_commit.repository.owner.username,
        project_name=head_commit.repository.name,
        base_sha=base_commit.commitid,
        head_sha=head_commit.commitid,
    )


def get_repository_url(repository: Repository) -> str:
    return SiteUrls.repository_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
        project_name=repository.name,
    )


def get_pull_url(pull: Pull) -> str:
    repository = pull.repository
    return SiteUrls.pull_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
        project_name=repository.name,
        pull_id=pull.pullid,
    )


def get_bundle_analysis_pull_url(pull: Pull) -> str:
    repository = pull.repository
    pull_url = SiteUrls.pull_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
        project_name=repository.name,
        pull_id=pull.pullid,
    )
    params = [QueryParams(name="dropdown", value="bundle")]
    return append_query_params_to_url(url=pull_url, params=params)


def get_pull_graph_url(pull: Pull, graph_filename: str, **kwargs) -> str:
    repository = pull.repository
    url = SiteUrls.pull_graph_url.get_url(
        base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
        project_name=repository.name,
        pull_id=pull.pullid,
        graph_filename=graph_filename,
    )
    encoded_kwargs = urlencode(kwargs)
    return f"{url}?{encoded_kwargs}"


def get_org_account_url(pull: Pull) -> str:
    repository = pull.repository
    return SiteUrls.org_acccount_url.get_url(
        dashboard_base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
    )


def get_members_url(pull: Pull) -> str:
    repository = pull.repository
    if not requires_license():
        return SiteUrls.members_url.get_url(
            dashboard_base_url=get_dashboard_base_url(),
            service_short=services_short_dict.get(repository.service),
            username=repository.owner.username,
        )
    else:
        return SiteUrls.members_url_self_hosted.get_url(
            dashboard_base_url=get_dashboard_base_url(),
            service_short=services_short_dict.get(repository.service),
            username=pull.author.username,
        )


def get_plan_url(pull: Pull) -> str:
    repository = pull.repository
    return SiteUrls.plan_url.get_url(
        dashboard_base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repository.service),
        username=repository.owner.username,
    )


def get_test_analytics_url(repo: Repository, commit: Commit) -> str:
    return SiteUrls.test_analytics_url.get_url(
        dashboard_base_url=get_dashboard_base_url(),
        service_short=services_short_dict.get(repo.service),
        username=repo.owner.username,
        project_name=repo.name,
        branch_name=quote_plus(commit.branch),
    )


@dataclass
class QueryParams:
    name: str
    value: str


def append_query_params_to_url(url: str, params: List[QueryParams]) -> str:
    parsed_url = urlparse(url)
    query_dict = parse_qs(parsed_url.query)
    # Add tracking parameters
    for param in params:
        query_dict[param.name] = param.value
    parsed_url = parsed_url._replace(query=urlencode(query_dict, doseq=True))
    return urlunparse(parsed_url)


def append_tracking_params_to_urls(
    input_string: str, service: str, notification_type: str, org_name: str
) -> str:
    """
    Append tracking parameters to markdown links pointing to a codecov urls in a given string, using regex to
    detect and modify the urls.

    Args:
        input_string (str): a string that may contain a markdown link to a Codecov url, for example: PR comments, Checks annotation.

    Returns:
        string: the string with tracking parameters appended to the Codecov url.

    Example:
        input: "This string has a [link](codecov.io/pulls) to a codecov url that will be changed (but we won't change this reference to codecov.io) since  it's not a Markdown link."
        output: "This string has a [link](codecov.io/pulls?<tracking params go here>) to a codecov url that will be changed (but we won't change this reference to codecov.io) since  it's not a Markdown link."

    """
    # regex matches against the pattern: ](<text>codecov.io<text>)
    # group 1 is "](", group 2 is the url, group 3 is ")"
    cond = re.compile(r"(\]\()(\S*?codecov\.io[\S]*?)(\))")

    # Function used during regex substitution to append params to the url
    def add_params(match):
        # Extract url from regex and parse the query string
        url = match.group(2)
        parsed_url = urlparse(url)
        query_dict = parse_qs(parsed_url.query)
        # Add tracking parameters
        query_dict["utm_medium"] = "referral"
        query_dict["utm_source"] = service
        query_dict["utm_content"] = notification_type
        query_dict["utm_campaign"] = "pr comments"
        query_dict["utm_term"] = org_name
        # Reconstruct the url with the new query string
        parsed_url = parsed_url._replace(query=urlencode(query_dict, doseq=True))
        url_with_tracking_params = urlunparse(parsed_url)

        return "](" + url_with_tracking_params + ")"

    return cond.sub(add_params, input_string)
