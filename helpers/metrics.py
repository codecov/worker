from statsd.defaults.env import statsd

KiB = 1024
MiB = KiB * KiB

metrics = statsd

# enumerates all the powers-of-two, from 8K all the way to 1G:
BYTE_SIZE_BUCKETS = [2**power for power in range(13, 31)]
