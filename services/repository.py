import logging
from json import dumps, loads

import torngit

from services.encryption import adjust_token

from helpers.config import config


log = logging.getLogger(__name__)

# TODO(Subhi/Thiago): this function needs to be re-written since it includes a lot of legacy old code

def get_repo(db_session, redis_connection, repoid, commitid=None, use_integration=True):
    # _timeouts = [
    #     config.get(('setup', 'http', 'timeouts', 'connect'), 15),
    #     config.get(('setup', 'http', 'timeouts', 'receive'), 30)
    # ]
    cache_key = 'repo@%s' % str(repoid)
    repo = redis_connection.get(cache_key)
    if repo:
        repo = loads(repo)
    else:
        repo = db_session.execute('SELECT get_repo(:repoid)', {'repoid': repoid})
        repo = repo.first()[0]
        redis_connection.setex(cache_key, 60, dumps(repo))
    assert repo, 'repo-not-found'
    # create the repo
    service = repo['service']
    # extract org_yaml
    org_yaml = repo.pop('org_yaml')

    key = None
    if (
        use_integration and
        service.startswith('github') and
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
        # TODO (Subhi/Thiago)
        # Yaml join was commented out for now so we don't bring code from the main app
        # that is not refactored
        # yaml=yaml_join(org_yaml, repo.pop('yaml')),
        repo=repo,
        verify_ssl=config.get_verify_ssl(service),
        org_yaml=org_yaml,  # we may use it later
        timeouts=_timeouts,
        oauth_consumer_token=dict(
            key=config.get((service, 'client_id')),
            secret=config.get((service, 'client_secret'))))
    repo.get_oauth_token = self.get_oauth_token
    return repo
