config = dict(
    logging=dict(
        loggers=dict(
            # Quiet this guy down...
            requests={
                "level": "WARNING",
                "propagate": True,
                "handlers": ["console"],
            },
#            coco={
#                "level": "INFO",
#                "propagate": True,
#                "handlers": ["console"],
#            },
        ),
    ),
)
