from base64 import encodestring, b16encode, b64encode

from helpers import config


def get_archive_hash(repository):
    assert repository.data['repo'].get('repoid') and repository.data['repo'].get('service_id'), (500, 'Missing information to build aws key.')
    _hash = md5()
    _hash.update(''.join((repository.data['repo']['repoid'],
                          repository.service,
                          repository.data['repo']['service_id'],
                          config.get(('services', 'minio', 'hash_key')) or '')))
    return b16encode(_hash.digest())


def delete_from_archive(path):
    conf = config.get(('services', 'minio'))
    date = datetime.now().strftime('%Y%m%dT%H%M%SZ')
    string_to_sign = '\n'.join(('DELETE', '', '', '', 'x-amz-date:%s' % date,
                                '/{}/{}'.format(conf['bucket'], path)))
    signature = hmac.new(config.get(('services', 'minio', 'access_key_id')).encode(),
                         string_to_sign.encode('utf-8', 'replace'), sha1).digest()
    requests.delete(
        '/'.join((get_archive_dsn(), path)),
        verify=conf['verify_ssl'],
        headers={
            'x-amz-date': date,
            'Authorization': 'AWS %s:%s' % (config.get(('services', 'minio', 'secret_access_key')), b64encode(signature))
        }
    )


def clean_archive():
    mc = get_minio_client()
    bucket = config.get(('services', 'minio', 'bucket'))
    uploads = mc.list_objects_v2(bucket, 'v4/raw/', recursive=False)
    expires = (
        datetime.now() -
        timedelta(days=-1*int(config.get(('services', 'minio', 'expire_raw_after_n_days'), 30)))
    )
    for obj in uploads:
        if datetime.strptime(obj.object_name.split('/')[2], '%Y-%m-%d') < expires:
            mc.remove_object(bucket, obj.object_name)


def get_from_archive(repository, commitid):
    conf = config.get(('services', 'minio'))
    key = get_archive_hash(repository)
    with metrics.timer('worker.archive.chunks.get'):
        res = requests.get(
            '{}/v4/repos/{}/commits/{}/chunks.txt'.format(
                get_archive_dsn(), key, commitid
            ),
            verify=conf['verify_ssl']
        )
        res.raise_for_status()
        return res.text


def get_archive_dsn(internally=True):
    conf = config.get(('services', 'minio'), {})
    dsn = conf.get('dsn')
    if dsn:
        if internally:
            return 'http://{}:{}/{}'.format(
                os.getenv('MINIO_PORT_9000_TCP_ADDR', 'minio'),
                os.getenv('MINIO_PORT_9000_TCP_PORT', '9000'),
                conf['bucket']
            )
        else:
            return '%s/%s' % (dsn, conf['bucket'])


def get_minio_client():
    minio_config = config.get(('services', 'minio'))
    return minio.Minio(
        '{}:{}'.format(
            os.getenv('MINIO_PORT_9000_TCP_ADDR', 'minio'),
            os.getenv('MINIO_PORT_9000_TCP_PORT', '9000')
        ),
        access_key=minio_config['access_key_id'],
        secret_key=minio_config['secret_access_key'],
        secure=minio_config['verify_ssl']
    )


def setup_bucket():
    minio_config = config.get(('services', 'minio'))
    mc = get_minio_client()
    mc.make_bucket(minio_config['bucket'],
                   location=minio_config.get('region', 'us-east-1'))
    mc.set_bucket_policy(minio_config['bucket'], '*',
                         minio.policy.Policy.READ_ONLY)
