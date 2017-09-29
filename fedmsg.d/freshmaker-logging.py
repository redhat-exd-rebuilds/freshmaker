config = dict(
    logging=dict(
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
            # freshmaker={
            #     "level": "INFO",
            #     "propagate": True,
            #     "handlers": ["console"],
            # },
        ),
    ),
)
