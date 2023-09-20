# -*- coding: utf-8 -*-
# Copyright (c) 2019  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import flask
import mock
import os
import pytest

from gql.dsl import DSLSchema
from graphql import build_ast_schema, parse


@pytest.fixture(autouse=True)
def clear_flask_g():
    """
    Clear the Flask global variables after each test.

    Many of the tests end up modifying flask.g such as for testing or mocking authentication.
    If it isn't cleared, it would end up leaking into other tests which don't expect it.
    """
    for attr in ("group", "user"):
        if hasattr(flask.g, attr):
            delattr(flask.g, attr)


@pytest.fixture()
def pyxis_graphql_schema():
    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    with mock.patch(
        "freshmaker.pyxis_gql.PyxisGQL.dsl_schema", new_callable=mock.PropertyMock
    ) as dsl_schema:
        dsl_schema.return_value = DSLSchema(schema)
        yield dsl_schema
