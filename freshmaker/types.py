# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from enum import Enum
from freshmaker.monitor import (
    freshmaker_artifact_build_done_counter,
    freshmaker_artifact_build_failed_counter,
    freshmaker_artifact_build_canceled_counter,
    freshmaker_event_complete_counter, freshmaker_event_failed_counter,
    freshmaker_event_skipped_counter)


class ArtifactType(Enum):
    RPM = 0
    IMAGE = 1
    MODULE = 2


class ArtifactBuildState(Enum):

    def __init__(self, value, counter):
        self._value_ = value
        self.counter = counter

    BUILD = (0, None)
    DONE = (1, freshmaker_artifact_build_done_counter)
    FAILED = (2, freshmaker_artifact_build_failed_counter)
    CANCELED = (3, freshmaker_artifact_build_canceled_counter)
    PLANNED = (4, None)


class EventState(Enum):

    def __init__(self, value, counter):
        self._value_ = value
        self.counter = counter

    INITIALIZED = (0, None)
    # some artifacts has been found and under building
    BUILDING = (1, None)
    # event is handled successfully
    COMPLETE = (2, freshmaker_event_complete_counter)
    # error happens while handling the event
    FAILED = (3, freshmaker_event_failed_counter)
    # no action to take upon the event
    SKIPPED = (4, freshmaker_event_skipped_counter)
