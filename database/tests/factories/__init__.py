from uuid import uuid4

import factory
from database import models
from hashlib import sha1
from factory import Factory

from services.encryption import encryptor


class OwnerFactory(Factory):
    class Meta:
        model = models.Owner
        exclude = ('unencrypted_oauth_token',)

    name = factory.Faker('name')
    username = factory.Faker('user_name')
    plan_activated_users = []
    admins = []
    permission = []
    service = 'github'
    free = 0
    unencrypted_oauth_token = factory.LazyFunction(lambda: uuid4().hex)

    oauth_token = factory.LazyAttribute(lambda o: encryptor.encode(o.unencrypted_oauth_token))


class RepositoryFactory(Factory):
    class Meta:
        model = models.Repository

    private = True
    name = 'example-python'
    using_integration = False

    owner = factory.SubFactory(OwnerFactory)
    bot = None


class CommitFactory(Factory):
    class Meta:
        model = models.Commit

    message = factory.Faker('sentence')

    commitid = factory.LazyAttribute(lambda o: sha1(o.message.encode('utf-8')).hexdigest())
    ci_passed = True
    pullid = 1
    author = factory.SubFactory(OwnerFactory)
    repository = factory.SubFactory(RepositoryFactory)
    totals = {
        'C': 0,
        'M': 0,
        'N': 0,
        'b': 0,
        'c': '85.00000',
        'd': 0,
        'diff': [1, 2, 1, 1, 0, '50.00000', 0, 0, 0, 0, 0, 0, 0],
        'f': 3,
        'h': 17,
        'm': 3,
        'n': 20,
        'p': 0,
        's': 1
    }
    report = {
        'files': {
            'awesome/__init__.py': [
                2,
                [0, 10, 8, 2, 0, '80.00000', 0, 0, 0, 0, 0, 0, 0],
                [
                    [0, 10, 8, 2, 0, '80.00000', 0, 0, 0, 0, 0, 0, 0]
                ],
                [
                    0, 2, 1, 1, 0, '50.00000', 0, 0, 0, 0, 0, 0, 0
                ]
            ],
            'tests/__init__.py': [
                0,
                [
                    0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0
                ],
                [
                    [0, 3, 2, 1, 0, '66.66667', 0, 0, 0, 0, 0, 0, 0]
                ],
                None
            ],
            'tests/test_sample.py': [
                1,
                [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0],
                [
                    [0, 7, 7, 0, 0, '100', 0, 0, 0, 0, 0, 0, 0]
                ],
                None
            ]
        },
        'sessions': {
            '0': {
                'N': None,
                'a': 'v4/raw/2019-01-10/4434BC2A2EC4FCA57F77B473D83F928C/abf6d4df662c47e32460020ab14abf9303581429/9ccc55a1-8b41-4bb1-a946-ee7a33a7fb56.txt',
                'c': None,
                'd': 1547084427,
                'e': None,
                'f': None,
                'j': None,
                'n': None,
                'p': None,
                't': [
                    3, 20, 17, 3, 0, '85.00000', 0, 0, 0, 0, 0, 0, 0
                ],
                '': None
            }
        }
    }
    parent_commit_id = factory.LazyAttribute(lambda o: sha1((o.message + "parent").encode('utf-8')).hexdigest())
    state = 'complete'
