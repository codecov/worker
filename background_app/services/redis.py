from redis import Redis


def get_redis_connection():
    return Redis(host='localhost', port=6379, db=0)
