config_dict = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
        'json': {
            'format': '%(message)s %(asctime)s %(name)s %(levelname)s',
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter'
        },
    },
    'root': {  # root logger
        'handlers': ['default'],
        'level': 'INFO',
        'propagate': True
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'json',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',  # Default is stderr
        },
    },
    'loggers': {}
}
