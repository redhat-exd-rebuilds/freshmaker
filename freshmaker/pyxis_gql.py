#!/usr/bin/env python

from functools import cached_property

from gql import gql, Client
from gql.dsl import DSLQuery, DSLSchema, dsl_gql
from gql.transport.requests import RequestsHTTPTransport


class PyxisGQLRequestError(RuntimeError):
    pass


class RequestsHTTPTransportWithCert(RequestsHTTPTransport):
    """A modified requests transport to support certificate authentication"""

    def __init__(self, *args, **kwargs):
        self.cert = kwargs.pop("cert", None)
        if self.cert is None:
            raise RuntimeError("Missing required keyword argument: cert")
        super().__init__(*args, **kwargs)

    def connect(self):
        super().connect()
        self.session.cert = self.cert


class PyxisGQL:
    def __init__(self, url, cert):
        """Create authenticated Pyxis GraphQL session"""
        transport = RequestsHTTPTransportWithCert(
            url=url,
            retries=3,
            cert=cert,
        )
        # Fetch the schema from the transport using an introspection query
        self._client = Client(transport=transport, fetch_schema_from_transport=True)

    @cached_property
    def dsl_schema(self):
        query = gql(
            """
                query {
                    get_ping
                }
            """
        )
        self._client.execute(query)
        return DSLSchema(self._client.schema)

    def query(self, query_dsl):
        """Execute a GraphQL query with Domain Specific Language

        :params gql.dsl.DSLField query_dsl: a DSL query
        :return: The result of execution.
        """
        return self._client.execute(dsl_gql(DSLQuery(query_dsl)))

    def find_repositories(self, published=None, release_categories=None, auto_rebuild_tags=None):
        """Get image repositories

        :param bool published: published or unpublished repositories
        :param list release_categories: list of release categories
        :param list auto_rebuild_tags: list of tags enabled for auto rebuild
        :return: list of image repositories
        :rtype: list
        """
        query_filter = {}
        query_filter["and"] = []
        # Query Red Hat repositories only
        query_filter["and"].append({"vendor_label": {"eq": "redhat"}})

        if published is not None and isinstance(published, bool):
            query_filter["and"].append({"published": {"eq": True}})

        if release_categories is not None:
            query_filter["and"].append({"release_categories": {"in": release_categories}})

        if auto_rebuild_tags is not None:
            query_filter["and"].append({"auto_rebuild_tags": {"in": auto_rebuild_tags}})

        repositories = []
        ds = self.dsl_schema

        page_num = 0
        page_size = 50
        # Iterate all pages
        while True:
            query_dsl = ds.Query.find_repositories(
                page=page_num,
                page_size=page_size,
                filter=query_filter,
            ).select(
                ds.ContainerRepositoryPaginatedResponse.error.select(
                    ds.ResponseError.status,
                    ds.ResponseError.detail,
                ),
                ds.ContainerRepositoryPaginatedResponse.page,
                ds.ContainerRepositoryPaginatedResponse.page_size,
                ds.ContainerRepositoryPaginatedResponse.total,
                ds.ContainerRepositoryPaginatedResponse.data.select(
                    ds.ContainerRepository.release_categories,
                    ds.ContainerRepository.auto_rebuild_tags,
                    ds.ContainerRepository.registry,
                    ds.ContainerRepository.repository,
                ),
            )

            result = self.query(query_dsl)
            error = result["find_repositories"]["error"]
            if error is not None:
                raise PyxisGQLRequestError(str(error))
            data = result["find_repositories"]["data"]
            # Data is empty when there are no more results
            if not data:
                break
            repositories.extend(data)
            page_num += 1

        return repositories
