import logging
from datetime import datetime
from enum import Enum, auto
from functools import lru_cache

from shared.license import get_current_license
from shared.config import get_config
from sqlalchemy import func

from database.models import Owner, Repository
from helpers.environment import is_enterprise

log = logging.getLogger(__name__)


class InvalidLicenseReason(Enum):
    invalid = auto()
    no_license = auto()
    unknown = auto()
    expired = auto()
    demo_mode = auto()
    url_mismatch = auto()
    users_exceeded = auto()
    repos_exceeded = auto()


def is_properly_licensed(db_session) -> bool:
    return not requires_license() or has_valid_license(db_session)


def requires_license():
    return is_enterprise()


def _get_now():
    return datetime.now()


def has_valid_license(db_session) -> bool:
    return reason_for_not_being_valid(db_session) is None


def reason_for_not_being_valid(db_session) -> InvalidLicenseReason:
    return cached_reason_for_not_being_valid(db_session)


@lru_cache()
def cached_reason_for_not_being_valid(db_session):
    return calculate_reason_for_not_being_valid(db_session)


def calculate_reason_for_not_being_valid(db_session):
    current_license = get_current_license()
    if not current_license.is_valid:
        return InvalidLicenseReason.invalid
    if current_license.url:
        if get_config("setup", "codecov_url") != current_license.url:
            return InvalidLicenseReason.url_mismatch
    if current_license.number_allowed_users:
        query = (
            db_session.query(func.count(), Owner.service)
            .filter(Owner.oauth_token.isnot(None))
            .group_by(Owner.service)
            .all()
        )
        for result in query:
            if result[0] > current_license.number_allowed_users:
                return InvalidLicenseReason.users_exceeded
            elif result[0] > (current_license.number_allowed_users - 10):
                log.warning(
                    "Number of users is approaching license limit of %d/%d for %s.",
                    result[0],
                    current_license.number_allowed_users,
                    result[1].upper(),
                )
    if current_license.number_allowed_repos:
        repos = (
            db_session.query(func.count())
            .select_from(Repository)
            .filter(Repository.updatestamp.isnot(None))
            .first()[0]
        )
        if repos > current_license.number_allowed_repos:
            return InvalidLicenseReason.repos_exceeded
        elif repos > (current_license.number_allowed_repos * 0.85):
            log.warning(
                "Number of repositories is approaching license limit of %d/%d",
                repos,
                current_license.number_allowed_repos,
            )
    if current_license.expires:
        if current_license.expires < _get_now():
            return InvalidLicenseReason.expired
    return None
