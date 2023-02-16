# [x] create a new python virtual environment based on the freshmaker env, and install the dependencies for kerberos and python gssapi
# - pacotes que instalei e que não estavam nas dependêncvias: krb5, gssapi

# [x] try to establish a connection with pyxis server via curl (https://pyxis.engineering.redhat.com/docs/access-request.html)

# [x] make a succesfull request using requests-kerberos + requests to that endpoint; use rq+krb class HTTPKerberosAuth to add kerb authentication info to the request

# [x] make a new enveloper in the pyxis module to set krb connection to the pyxis server

# [x] fork the freshmaker repo, make a new branch in it and start contributing to my fork; leave master branch as it is to properly check the setup before testing
# [x] write a makefile, install tools, lint and check the code
# [x] commit the prototype file i made so far

# [x] make a backup file of pyxis_gql.py
# [x] insert the kerberos functionality in pyxis_gql.py ()
# - seems like requests-kerberos has this class that attaches kerberos/gssapi auth to a given request:
#   https://github.com/requests/requests-kerberos/blob/master/requests_kerberos/kerberos_.py#L165
# [ ] make type hints?

# [ ] test that all queries are working fine in local pyxis
# [ ] test that all queries are working fine in remote pyxis
# [ ] run unit tests and rewrite whatever needs correction
# [ ] remove backup of old pyxis_gql.py
# [ ] format and lint
# [ ] commit

# [ ] later: check if not verifying ssl certificates is ok
# [ ] later: check if not making mutual authentication is ok
# [ ] later: check if freshmaker has a service credential in pyxis, and if not request one
# [ ] later: figure out how kinit will be run before pyxis queries are sent (TGT whould already be present in the by the time the query is set up)

# [ ] merge request my fork into the original repo (into master branch?)
# [ ] later: perguntar sobre incluir o makefile e steps na action para verificar o código (bandit com pré-commit, flake8/black pos commit)


# kinit mfoganho@IPA.REDHAT.COM
# curl --negotiate -u : -b ~/cookiejar.txt -c ~/cookiejar.txt  https://pyxis.dev.engineering.redhat.com/v1/product-listings
#   - --negotiate -u : -> uses kerberos authenitcation
#   - -b and -c -> spit cookie headers/cookiejar contents to the pointes files
# OK # curl 'https://graphql.pyxis.dev.engineering.redhat.com/graphql/' -H 'Accept-Encoding: gzip, deflate, br' -H 'Content-Type: application/json' -H 'Accept: application/json' -H 'Connection: keep-alive' -H 'DNT: 1' -H '' --data-binary '{"query":"# Try to write your query here\n{\n  get_ping\n}"}' --compressed
# NOK # curl --negotiate -u : 'https://graphql.pyxis.dev.engineering.redhat.com/graphql/' -H 'Accept-Encoding: gzip, deflate, br' -H 'Content-Type: application/json' -H 'Accept: application/json' -H 'Connection: keep-alive' -H 'DNT: 1' -H '' --data-binary '{"query":"# Try to write your query here\n{\n    find_images(page_size: 3, sort_by: [{ field: \"creation_date\", order: DESC }]) {\n        error {\n            status\n            detail\n        }\n        page\n        page_size\n        total\n        data {\n            _id\n            creation_date\n        }\n    }\n}"}' --compressed
# OK # curl --negotiate -u : 'https://graphql.pyxis.dev.engineering.redhat.com/graphql/' -H 'Accept-Encoding: gzip, deflate, br' -H 'Content-Type: application/json' -H 'Accept: application/json' -H 'Connection: keep-alive' -H 'DNT: 1' -H '' --data-binary '{"query":"{\n  find_images(page: 0, page_size: 50) {\n    error {\n      detail\n      status\n    }\n\n    #total # omit for better performance\n    page_size\n    page\n\n    data {\n      _id\n    }\n  }\n}"}' --compressed


import logging

import certifi
import requests
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport
from requests_kerberos import DISABLED, OPTIONAL, REQUIRED, HTTPKerberosAuth

logging.basicConfig()
logging.getLogger().setLevel(logging.DEBUG)


def try_request() -> requests.Response:
    pyxis_url = "https://pyxis.engineering.redhat.com/v1/product-listings"
    # pyxis_url="https://pyxis.engineering.redhat.com/v1/ping"
    pyxis_krb_auth = HTTPKerberosAuth(
        mutual_authentication=OPTIONAL,
    )

    res = requests.get(url=pyxis_url, auth=pyxis_krb_auth, verify=False)
    print(res)
    print(res.content)

    return res


# [x] ping query working (dev ok, non dev: ok)
# [x] find query 2 working (dev ok, non dev: ok)
# [x] find query working (dev ok, non dev: ok) -> but only without 'total'
def try_query() -> dict:
    pyxis_url = "https://graphql.pyxis.dev.engineering.redhat.com/graphql/"
    pyxis_krb_auth = HTTPKerberosAuth(
        mutual_authentication=OPTIONAL, force_preemptive=True
    )
    pyxis_krb_transport = RequestsHTTPTransport(
        url=pyxis_url,
        retries=3,
        auth=pyxis_krb_auth,
        method="POST",
        verify=False,
    )
    pyxis_client = Client(
        transport=pyxis_krb_transport, fetch_schema_from_transport=True
    )

    ping_query = gql(
        """
        query {
            get_ping
        }
    """
    )
    find_query = gql(
        """
        {
            find_images(page_size: 3, sort_by: [{ field: "creation_date", order: DESC }]) {
                error {
                    status
                    detail
                }
                page
                page_size
                #total
                data {
                    _id
                    creation_date
                }
            }
        }
    """
    )
    find_query2 = gql(
        """
        {
            find_images(page: 0, page_size: 50) {
                error {
                detail
                status
                }

                #total # omit for better performance
                page_size
                page

                data {
                _id
                }
            }
        }
        """
    )
    res = pyxis_client.execute(find_query)
    print(res)
    print(res.keys())

    return res


if __name__ == "__main__":
    # res = try_request()
    res = try_query()


# class PyxisGQL:
#     def __init__(self, url, cert):
#         """Create authenticated Pyxis GraphQL session"""
#         pyxis_krb_auth = HTTPKerberosAuth(
#             ...
#         )
#         transport = RequestsHTTPTransportWithCert(
#             url=url,
#             retries=3,
#             auth=pyxis_krb_auth
#         )
#         # Fetch the schema from the transport using an introspection query
#         self._client = Client(transport=transport, fetch_schema_from_transport=True)

#     # ...
