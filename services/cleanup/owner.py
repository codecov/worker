from django.db import transaction
from django.db.models import Q
from shared.django_apps.codecov_auth.models import Owner
from shared.django_apps.core.models import Commit, Pull, Repository

CLEAR_ARRAY_FIELDS = ["plan_activated_users", "organizations", "admins"]


def clear_owner(owner_id: int):
    """
    This clears the `ownerid` from various DB arrays where it is being referenced.
    """

    Owner.objects.filter(bot=owner_id).update(bot=None)
    Repository.objects.filter(bot=owner_id).update(bot=None)
    Commit.objects.filter(author=owner_id).update(author=None)
    Pull.objects.filter(author=owner_id).update(author=None)

    with transaction.atomic():
        filter = Q()
        for field in CLEAR_ARRAY_FIELDS:
            filter = filter | Q(**{f"{field}__contains": [owner_id]})

        owners_with_reference = Owner.objects.select_for_update().filter(filter)
        for owner in owners_with_reference:
            for field in CLEAR_ARRAY_FIELDS:
                array = getattr(owner, field)
                setattr(owner, field, [x for x in array if x != owner_id])

            owner.save(update_fields=CLEAR_ARRAY_FIELDS)
