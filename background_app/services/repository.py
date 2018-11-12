import logging
from json import dumps, loads

import torngit
from app import config

from app.helpers import yaml_join
from config import PEM
from database.engine import get_db_session
from services.encryption import adjust_token
from services.redis import get_redis_connection

log = logging.getLogger(__name__)


def get_repo(repoid, commitid=None, use_integration=True):
    _timeouts = [
        config.get(('setup', 'http', 'timeouts', 'connect'), 15),
        config.get(('setup', 'http', 'timeouts', 'receive'), 30)
    ]
    db = get_db_session()
    redis = get_redis_connection()
    cache_key = 'repo@%s' % str(repoid)
    repo = redis.get(cache_key)
    if repo:
        repo = loads(repo)
    else:
        repo = db.get("SELECT get_repo(%s::int) limit 1;", repoid)['get_repo']
        redis.setex(cache_key, 60, dumps(repo))
    assert repo, 'repo-not-found'
    # create the repo
    service = repo['service']
    # extract org_yaml
    org_yaml = repo.pop('org_yaml')

    key = None
    if (
        use_integration and
        service.startswith('github') and
        PEM.get(service) and
        repo.get('integration_id')
    ):
        key = get_github_integration_token(service, repo.pop('integration_id'))
        if key:
            repo['token'] = dict(username='n/a', key=key)
            repo['using_integration'] = True

    if not key:
        # adjust the token
        adjust_token(repo['token'])
        repo['using_integration'] = False

    # return repo
    repo = torngit.get(
        service,
        log_handler=log,
        owner=dict(
            service_id=repo.pop('owner_service_id'),
            ownerid=repo.pop('ownerid'),
            username=repo.pop('username')),
        _yaml_location=repo.pop('_yaml_location'),
        token=repo.pop('token') or config.get((service, 'bot')),
        yaml=yaml_join(org_yaml, repo.pop('yaml')),
        repo=repo,
        verify_ssl=config.get_verify_ssl(service),
        org_yaml=org_yaml,  # we may use it later
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=config.get((service, 'client_id')),
            secret=config.get((service, 'client_secret'))))
    repo.get_oauth_token = self.get_oauth_token
    return repo
