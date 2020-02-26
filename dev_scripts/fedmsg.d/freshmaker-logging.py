config = dict(logging={
    "version": 1,
    "formatters": {
        "bare": {
        "datefmt": "%Y-%m-%d %H:%M:%S",
        "format": "[%(asctime)s][%(name)10s %(levelname)7s] %(message)s"
        }
    },
    "loggers": {
        "freshmaker": {
            "handlers": ["console"], "propagate": False, "level": "DEBUG"},
        "fedmsg": {
            "handlers": ["console"], "propagate": False, "level": "INFO"},
        "moksha": {
            "handlers": ["console"], "propagate": False, "level": "INFO"},
        "requests": {
            "level": "WARNING",
            "propagate": True,
            "handlers": ["console"],
        },
        "requests_kerberos": {
            "level": "WARNING",
            "propagate": True,
            "handlers": ["console"],
        },
        "dogpile": {
            "level": "WARNING",
            "propagate": True,
            "handlers": ["console"],
        },
    },
    "handlers": {
        "console": {
            "formatter": "bare",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "level": "DEBUG"
        }
    },
})
