config = dict(
    logging=dict(
        handlers={
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'bare',
                'level': 'INFO',
                'stream': 'ext://sys.stdout',
            },
        },
        formatters={
            'bare': {
                'datefmt': '%Y-%m-%d %H:%M:%S',
                'format': '[%(asctime)s][%(name)10s %(levelname)7s] %(message)s',
            },
        },
        loggers=dict(
            # Quiet these guys down...
            requests={
                "level": "WARNING",
                "propagate": True,
                "handlers": ["console"],
            },
            requests_kerberos={
                "level": "WARNING",
                "propagate": True,
                "handlers": ["console"],
            },
            dogpile={
                "level": "WARNING",
                "propagate": True,
                "handlers": ["console"],
            },
            proton={
                "level": "INFO",
                "propagate": True,
                "handlers": ["console"],
            },
            # freshmaker={
            #     "level": "INFO",
            #     "propagate": True,
            #     "handlers": ["console"],
            # },
        ),
        version=1,
    ),
)
