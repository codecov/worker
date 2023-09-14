import logging
from typing import Callable, Dict

from shared.encryption.token import encode_token

from database.models.core import Owner
from services.encryption import encryptor

log = logging.getLogger(__name__)


def get_token_refresh_callback(owner: Owner) -> Callable[[Dict], None]:
    """
    Produces a callback function that will encode and update the oauth token of a user.
    This callback is passed to the TorngitAdapter for the service.
    """
    # Some tokens don't have to be refreshed (GH integration, default bots)
    # They don't belong to any owners.
    if owner is None:
        return None

    service = owner.service
    if service == "bitbucket" or service == "bitbucket_server":
        return None

    async def callback(new_token: Dict) -> None:
        log.info(
            "Saving new token after refresh",
            extra=dict(owner=owner.username, ownerid=owner.ownerid),
        )
        string_to_save = encode_token(new_token)
        oauth_token = encryptor.encode(string_to_save).decode()
        owner.oauth_token = oauth_token

    return callback
