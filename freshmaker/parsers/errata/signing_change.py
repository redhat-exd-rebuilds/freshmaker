# SPDX-License-Identifier: MIT

from freshmaker.parsers import BaseParser
from freshmaker.events import FlatpakModuleAdvisoryReadyEvent
from freshmaker.errata import Errata, ErrataAdvisory


class ErrataAdvisorySigningChangedParser(BaseParser):
    """
    Parses errata.activity.signing messages (a build attached to advisory is
    signed).

    Creates FlatpakModuleAdvisoryReadyEvent if a new flatpak advisory can be
    created for module security advisory.
    """

    name = "ErrataAdvisorySigningChangedParser"
    topic_suffixes = ["errata.activity.signing"]

    def can_parse(self, topic, msg):
        return any(topic.endswith(s) for s in self.topic_suffixes)

    def parse(self, topic, msg):
        msg_id = msg.get("msg_id")
        inner_msg = msg.get("msg")

        if "module" not in inner_msg["content_types"] or inner_msg["errata_status"] != "QE":
            return

        errata_id = int(inner_msg.get("errata_id"))
        errata = Errata()
        advisory = ErrataAdvisory.from_advisory_id(errata, errata_id)

        if advisory.is_flatpak_module_advisory_ready():
            return FlatpakModuleAdvisoryReadyEvent(msg_id, advisory)
