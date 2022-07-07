# -*- coding: utf-8 -*-
#
# Copyright (c) 2022  Red Hat, Inc.
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

import os
from flexmock import flexmock
from gql import Client
from gql.dsl import DSLSchema
from graphql import build_ast_schema, parse

from freshmaker.pyxis_gql import PyxisGQL


def test_pyxis_graphql_find_repositories():

    pyxis_schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "pyxis.graphql",
    )
    with open(pyxis_schema_path) as source:
        document = parse(source.read())
    schema = build_ast_schema(document)

    flexmock(PyxisGQL).should_receive("dsl_schema").and_return(DSLSchema(schema))

    results = [
        {
            "find_repositories": {
                "data": [
                    {
                        "auto_rebuild_tags": ["latest"],
                        "registry": "registry.example.com",
                        "release_categories": ["Generally Available"],
                        "repository": "foobar/foo",
                    },
                    {
                        "auto_rebuild_tags": ["latest"],
                        "registry": "registry.example.com",
                        "release_categories": ["Generally Available"],
                        "repository": "foobar/bar",
                    },
                ],
                "error": None,
                "page": 0,
                "page_size": 2,
                "total": 2,
            }
        },
        {
            "find_repositories": {
                "data": [],
                "error": None,
                "page": 1,
                "page_size": 2,
                "total": 2,
            }
        },
    ]

    pyxis_gql = PyxisGQL(url="graphql.pyxis.local", cert=("/path/to/crt", "/path/to/key"))
    flexmock(Client).should_receive("execute").and_return(results).one_by_one()

    repositories = pyxis_gql.find_repositories()

    assert repositories == results[0]["find_repositories"]["data"]
