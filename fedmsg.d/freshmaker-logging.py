config = dict(
    logging=dict(
        loggers=dict(
            # Quiet this guy down...
            requests={
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
