import logging
from uuid import uuid4

from django.db import DatabaseError, IntegrityError, transaction
from shared.django_apps.codecov_auth.models import Owner
from shared.django_apps.core.models import Repository

from services.cleanup.cleanup import run_cleanup
from services.cleanup.utils import CleanupResult, CleanupSummary

log = logging.getLogger(__name__)


def cleanup_repo(repo_id: int) -> CleanupSummary:
    try:
        cleanup_started, owner_id = start_repo_cleanup(repo_id)
    except Repository.DoesNotExist:
        log.warning("Repository does not exist / was already cleaned up")
        return CleanupSummary(CleanupResult(0), {})
    except (DatabaseError, IntegrityError) as _:
        # `DatabaseError` means that the `SELECT FOR UPDATE NOWAIT` is currently locked.
        # `IntegrityError` means that the `Owner.create` has a duplicated `service_id`.
        log.warning("Cleanup could not be started because of conflicting job")
        return CleanupSummary(CleanupResult(0), {})

    if cleanup_started:
        log.info("Started Repository cleanup")
    else:
        log.info("Continuing Repository cleanup")

    repo_query = Repository.objects.filter(repoid=repo_id)
    summary = run_cleanup(repo_query)

    # Delete the created "Shadow Owner" using a `raw_delete`, as otherwise this
    # would run some very slow and expensive `SET NULL` / `CASCADE` queries,
    # which are unnecessary as this shadow owner does not have any relations
    owner_query = Owner.objects.filter(ownerid=owner_id)
    owner_query._for_write = True  # Select the correct writable DB connection
    owner_query._raw_delete(owner_query.db)

    log.info("Repository cleanup finished", extra={"summary": summary})
    return summary


def start_repo_cleanup(repo_id: int) -> tuple[bool, int]:
    """
    Starts Repository deletion by marking the repository as `deleted`, and moving
    it to a newly created "shadow Owner".

    This newly created `Owner` only has a valid `service` and `service_id`,
    which are the only required non-NULL fields without defaults, and is otherwise
    completely empty.

    The `ownerid` of this newly created owner is being returned along with a flag
    indicating whether the repo cleanup was just started, or whether it is already
    marked for deletion, and this function is being retried.
    It is expected that repo cleanup is a slow process and might be done in more steps.
    """
    # Runs in a transaction as we do not want to leave leftover shadow owners in
    # case anything goes wrong here.
    with transaction.atomic():
        (
            repo_deleted,
            owner_id,
            owner_name,
            owner_username,
            owner_service,
            owner_service_id,
        ) = (
            Repository.objects.select_for_update(nowait=True)
            .values_list(
                "deleted",
                "author__ownerid",
                "author__name",
                "author__username",
                "author__service",
                "author__service_id",
            )
            .get(repoid=repo_id)
        )

        if repo_deleted and not owner_name and not owner_username:
            return (False, owner_id)

        # We mark the repository as "scheduled for deletion" by setting the `deleted`
        # flag, moving it to a new shadow owner, and clearing some tokens.
        shadow_owner = Owner.objects.create(
            # `Owner` is unique across service/id, and both are non-NULL,
            # so we cannot duplicate the values just like that, so lets change up the `service_id`
            # a bit. We need the `Repository.service_id` for further `ArchiveService` deletions.
            service=owner_service,
            service_id=f"☠️{owner_service_id}☠️",
        )
        new_token = uuid4().hex
        Repository.objects.filter(repoid=repo_id).update(
            deleted=True,
            author=shadow_owner,
            upload_token=new_token,
            image_token=new_token,
        )

    return (True, shadow_owner.ownerid)
