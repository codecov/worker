from typing import Optional, Tuple

from shared.typings.oauth_token_types import Token

from database.models.core import Owner

# A Token and its Owner
# If a Token doesn't belong to Owner (i.e. it's a GitHubAppInstallation Token), second value is None
type TokenWithOwner = Tuple[Token, Optional[Owner]]
