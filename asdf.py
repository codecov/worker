import os

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()

from shared.django_apps.codecov_auth.models import Owner
from shared.encryption.token import decode_token


me = Owner.objects.get(ownerid=1611)
print(me)
print(me.oauth_token)
print(decode_token(me.oauth_token))
