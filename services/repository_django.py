import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Tuple

import shared.torngit as torngit
from asgiref.sync import sync_to_async
from django.db.models import Q
from shared.config import get_config, get_verify_ssl
from shared.django_apps.codecov_auth.models import (
    GITHUB_APP_INSTALLATION_DEFAULT_NAME,
    Owner,
)
from shared.django_apps.core.models import Commit, Pull, Repository
from shared.torngit.exceptions import (
    TorngitClientError,
    TorngitError,
    TorngitObjectNotFoundError,
)
from shared.typings.torngit import (
    OwnerInfo,
    RepoInfo,
    TorngitInstanceData,
)

from helpers.token_refresh_django import get_token_refresh_callback
from services.bots_django import get_adapter_auth_information
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


@dataclass
class EnrichedPull(object):
    database_pull: Pull
    provider_pull: Mapping[str, Any] | None


def _is_repo_using_integration(repo: Repository) -> bool:
    owner = repo.author
    default_ghapp_installation = list(
        filter(
            lambda obj: obj.name == GITHUB_APP_INSTALLATION_DEFAULT_NAME,
            owner.github_app_installations.all() or [],
        )
    )
    if default_ghapp_installation:
        ghapp_installation = owner.github_app_installations.all()[0]
        return ghapp_installation.is_repo_covered_by_integration(repo)
    return repo.using_integration


@sync_to_async
def get_repo_provider_service(
    repository: Repository,
    installation_name_to_use: str | None = GITHUB_APP_INSTALLATION_DEFAULT_NAME,
) -> torngit.base.TorngitBaseAdapter:
    _timeouts = [
        get_config("setup", "http", "timeouts", "connect", default=30),
        get_config("setup", "http", "timeouts", "receive", default=60),
    ]

    service = repository.author.service
    adapter_auth_info = get_adapter_auth_information(
        repository.author,
        repository=repository,
        installation_name_to_use=installation_name_to_use,
    )
    data = TorngitInstanceData(
        repo=RepoInfo(
            name=repository.name,
            using_integration=_is_repo_using_integration(repository),
            service_id=repository.service_id,
            repoid=repository.repoid,
        ),
        owner=OwnerInfo(
            service_id=repository.author.service_id,
            ownerid=repository.author_id,
            username=repository.author.username,
        ),
        installation=adapter_auth_info["selected_installation_info"],
        fallback_installations=adapter_auth_info["fallback_installations"],
    )

    adapter_params = dict(
        token=adapter_auth_info["token"],
        token_type_mapping=adapter_auth_info["token_type_mapping"],
        verify_ssl=get_verify_ssl(service),
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=get_config(service, "client_id"),
            secret=get_config(service, "client_secret"),
        ),
        on_token_refresh=get_token_refresh_callback(adapter_auth_info["token_owner"]),
        **data,
    )
    return _get_repo_provider_service_instance(repository.service, **adapter_params)


def _get_repo_provider_service_instance(service_name, **adapter_params):
    return torngit.get(service_name, **adapter_params)


@sync_to_async
def get_head_commit(pull: Pull):
    return Commit.objects.filter(
        repository_id=pull.repository_id, commitid=pull.head
    ).first()


async def fetch_and_update_pull_request_information_from_commit(
    repository_service, commit, current_yaml
) -> EnrichedPull | None:
    pullid = commit.pullid
    if not commit.pullid:
        try:
            pullid = await repository_service.find_pull_request(
                commit=commit.commitid, branch=commit.branch
            )
            print(pullid)
        except TorngitClientError:
            log.warning(
                "Unable to fetch what pull request the commit belongs to",
                exc_info=True,
                extra=dict(repoid=commit.repository_id, commit=commit.commitid),
            )
    if not pullid:
        return None
    enriched_pull = await fetch_and_update_pull_request_information(
        repository_service, commit.repository_id, pullid, current_yaml
    )
    pull = enriched_pull.database_pull
    if pull is not None:
        head = await get_head_commit(pull)
        if head is None or head.timestamp <= commit.timestamp:
            pull.head = commit.commitid
    return enriched_pull


@sync_to_async
def get_pull_from_db(pullid, repoid):
    return Pull.objects.filter(pullid=pullid, repository_id=repoid).first()


@sync_to_async
def update_or_create_pull(pullid, repoid, pull_information):
    pull, _ = Pull.objects.update_or_create(
        pullid=pullid,
        repository_id=repoid,
        defaults={
            "issueid": int(pull_information["id"]),
            "state": pull_information["state"],
            "title": pull_information["title"],
        },
    )
    return pull


@sync_to_async
def get_val_of_new_base_query(new_base_query):
    return new_base_query.first()


@sync_to_async
def get_base_commit(pull_base_sha, repoid):
    return Commit.objects.filter(commitid=pull_base_sha, repository_id=repoid).first()


@sync_to_async
def save_pull(pull):
    pull.save()


@sync_to_async
def pull_author(pull):
    return pull.author


async def fetch_and_update_pull_request_information(
    repository_service, repoid, pullid, current_yaml
) -> EnrichedPull:
    try:
        pull_information = await repository_service.get_pull_request(pullid=pullid)
    except TorngitClientError:
        log.warning(
            "Unable to find pull request information on provider to update it due to client error",
            extra=dict(repoid=repoid, pullid=pullid),
        )

        pull = await get_pull_from_db(pullid, repoid)
        return EnrichedPull(database_pull=pull, provider_pull=None)
    except TorngitError:
        log.warning(
            "Unable to find pull request information on provider to update it due to unknown provider error",
            extra=dict(repoid=repoid, pullid=pullid),
        )
        pull = await get_pull_from_db(pullid, repoid)
        return EnrichedPull(database_pull=pull, provider_pull=None)

    pull = await update_or_create_pull(pullid, repoid, pull_information)

    base_commit_sha, compared_to = await _pick_best_base_comparedto_pair(
        repository_service, pull, current_yaml, pull_information
    )
    pull.base = base_commit_sha
    pull.compared_to = compared_to

    if pull is not None:
        pr_author = await get_or_create_author(
            repository_service.service,
            pull_information["author"]["id"],
            pull_information["author"]["username"],
        )
        if pr_author:
            pull.author = pr_author

    await save_pull(pull)

    return EnrichedPull(database_pull=pull, provider_pull=pull_information)


async def _pick_best_base_comparedto_pair(
    repository_service, pull, current_yaml, pull_information
) -> Tuple[str, str | None]:
    repoid = pull.repository_id
    candidates_to_base = (
        [pull.user_provided_base_sha, pull_information["base"]["commitid"]]
        if pull is not None and pull.user_provided_base_sha is not None
        else [pull_information["base"]["commitid"]]
    )
    for pull_base_sha in candidates_to_base:
        base_commit = await get_base_commit(pull_base_sha, repoid)
        if base_commit:
            return (pull_base_sha, pull_base_sha)
        try:
            commit_dict = await repository_service.get_commit(pull_base_sha)
            new_base_query = Commit.objects.filter(
                Q(pullid__isnull=True) | Q(merged=True),
                Q(timestamp__lt=commit_dict["timestamp"]),
                repository_id=repoid,
                branch=pull_information["base"]["branch"],
            )

            if read_yaml_field(current_yaml, ("codecov", "require_ci_to_pass"), True):
                new_base_query = new_base_query.filter(ci_passed=True)
            new_base_query = new_base_query.order_by("-timestamp")
            new_base = await get_val_of_new_base_query(new_base_query)
            if new_base:
                return (pull_base_sha, new_base.commitid)
        except TorngitObjectNotFoundError:
            log.warning(
                "Cannot find (in the provider) commit that is supposed to be the PR base",
                extra=dict(repoid=repoid, supposed_base=pull_base_sha),
            )
    return (candidates_to_base[0], None)


@sync_to_async
def get_or_create_author(service, service_id, username, email=None, name=None) -> Owner:
    author, _ = Owner.objects.get_or_create(
        service=service,
        service_id=str(service_id),
        defaults={
            "username": username,
            "name": name,
            "email": email,
            "createstamp": datetime.now(),
        },
    )
    return author
