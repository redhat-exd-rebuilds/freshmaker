import dogpile.cache
import requests
import urllib
from datetime import datetime
from requests_kerberos import HTTPKerberosAuth, OPTIONAL
from packaging import version

from freshmaker import log, conf
from freshmaker.utils import get_ocp_release_date


class PyxisRequestError(Exception):
    """
    Error return as a response from Pyxis
    """

    def __init__(self, status_code, error_response):
        """
        Initialize Pyxis request error

        :param int status_code: response status code
        :param str or dict error_response: response content returned from Pyxis
        """

        self._status_code = status_code
        self._raw = error_response

    @property
    def raw(self):
        return self._raw

    @property
    def status_code(self):
        return self._status_code


class Pyxis(object):
    """ Interface for querying Pyxis"""

    region = dogpile.cache.make_region().configure(conf.dogpile_cache_backend)

    def __init__(self, server_url):
        self._server_url = server_url
        # add api version to root url
        self._api_root = urllib.parse.urljoin(self._server_url, "v1/")

    def _make_request(self, entity, params):
        """
        Send a request to Pyxis

        :param str entity: entity part to construct a full URL for request.
        :param dict params: Pyxis query parameters.
        :return: Json response from Pyxis
        :rtype: dict
        :raises PyxisRequestError: If Pyxis returns error as a response
        """
        entity_url = urllib.parse.urljoin(self._api_root, entity)

        auth_method = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
        response = requests.get(entity_url, params=params, auth=auth_method,
                                timeout=conf.net_timeout)

        if response.ok:
            return response.json()

        # Warn early, in case there is an error in the error handling code below
        log.warning("Request to %s gave %r", response.request.url, response)

        try:
            response_text = response.json()
        except ValueError:
            response_text = response.text

        raise PyxisRequestError(response.status_code, response_text)

    def _get(self, path, params=None):
        """
        Pyxis API GET request to a single resource

        :param str path: url path of the resource
        :param dict params: parameters of GET request
        :return: a single resource represented by a dict
        :rtype: dict
        """
        query_params = {}
        if params:
            query_params.update(params)

        return self._make_request(path, params=query_params)

    def _pagination(self, entity, params):
        """
        Process all pages in Pyxis

        :param str entity: what data/entity to request from Pyxis
        :param dict params: parameters to add to GET request
        :return: list of all 'data' fields from responses from Pyxis
        :rtype: list
        """
        local_params = {"page_size": "100"}
        local_params.update(params)
        ret = []
        page = 0
        while True:
            local_params["page"] = page
            response_data = self._make_request(entity, params=local_params)
            # When the page after the actual last page is reached, data will be an empty list
            if not response_data.get('data'):
                break
            ret.extend(response_data['data'])
            page += 1

        return ret

    def get_operator_indices(self):
        """ Get all index images for organization(s)(configurable) from Pyxis """
        request_params = {}
        organization = conf.pyxis_index_image_organization
        if organization:
            request_params["filter"] = "organization==" + organization
        indices = self._pagination("operators/indices", request_params)

        # Operator indices can be available in pyxis prior to the Openshift version
        # is released, so we need to filter out such indices
        indices = list(filter(lambda x: self.ocp_is_released(x["ocp_version"]), indices))
        return indices

    @region.cache_on_arguments()
    def ocp_is_released(self, ocp_version):
        """ Check if ocp_version is released by comparing the GA date with current date

        :param str ocp_version: the OpenShift Version
        :return: True if GA date in Product Pages is in the past, otherwise False
        :rtype: bool
        """
        ga_date_str = get_ocp_release_date(ocp_version)
        # None is returned if GA date is not found
        if not ga_date_str:
            log.warning(
                f"GA date of OpenShift {ocp_version} is not found in Product Pages, ignore it"
            )
            return False

        return datetime.now() > datetime.strptime(ga_date_str, "%Y-%m-%d")

    def _get_bundles_per_index_image(self, index_images):
        """
        Get bundle images for all index images

        :param list index_images: list of index images to get bundle images for
        :return: bundle images per index image
        :rtype: dict
        """
        bundles_per_index_image = {}
        # we need 'bundle_path_digest' to find ContainerImage of that bundle
        include_fields = ['data.channel_name', 'data.version',
                          'data.related_images', 'data.bundle_path_digest',
                          'data.bundle_path']
        request_params = {'include': ','.join(include_fields)}
        for index_image in index_images:
            path = index_image.get('path', '')
            if not path:
                continue
            request_params['filter'] = f"source_index_container_path=={path}"
            bundles_per_index_image[path] = self._pagination(
                'operators/bundles',
                request_params)

        return bundles_per_index_image

    def get_latest_bundles(self, index_images):
        """
        Get latest bundle images per channel per index image

        :param list index_images: list of index images
        :return: latest bundle images per channel per index image
        :rtype: list
        """
        bundles_per_index_image = \
            self._get_bundles_per_index_image(index_images)

        ret_bundles = []
        for index_image, bundles in bundles_per_index_image.items():
            bundle_per_channel = {}
            # get latest versions of bundle images per channel
            for bundle in bundles:
                channel = bundle['channel_name']
                try:
                    # Always ensure the new version is a valid semantic version
                    new_ver = version.Version(bundle['version'])
                    if channel in bundle_per_channel:
                        old_ver = version.Version(
                            bundle_per_channel[channel]['version'])
                        if new_ver > old_ver:
                            bundle_per_channel[channel] = bundle
                    else:
                        bundle_per_channel[channel] = bundle
                # Check if the right format of version is used
                except version.InvalidVersion as e:
                    path = bundle.get('bundle_path', 'Unknown bundle path')
                    log.warning("Other format than SemVer is used in "
                                "bundle: %s", path)
                    log.warning(repr(e))
            ret_bundles.extend(bundle_per_channel.values())

        return ret_bundles

    def get_manifest_list_digest_by_nvr(self, nvr):
        """
        Get image's digest(manifest_list_digest field) by its NVR

        :param str nvr: NVR of ContainerImage to query Pyxis
        :return: digest of image or None if manifest_list_digest not exists
        :rtype: str or None
        """
        request_params = {'include': ','.join(['data.brew', 'data.repositories'])}

        # get manifest_list_digest of ContainerImage from Pyxis
        for image in self._pagination(f'images/nvr/{nvr}', request_params):
            for repo in image.get('repositories'):
                if repo['published'] and 'manifest_list_digest' in repo:
                    return repo['manifest_list_digest']
        return None

    def get_bundles_by_related_image_digest(self, image_digest, bundles):
        """
        Get bundles that have the specified image digest in related images.

        :param str image_digest: digest of related image
        :param list bundles: list of bundles to search from
        :return: list of bundles
        :rtype: list
        """
        ret = []
        for bundle in bundles:
            if any(image_digest == img.get('digest') for img in bundle.get('related_images', [])):
                ret.append(bundle)

        return ret

    def get_images_by_digest(self, digest):
        """
        Get images by image's digest (manifest_list_digest or manifest_schema2_digest)

        :param str digest: digest of image
        :return: bundle images
        :rtype: list
        """
        q_filter = (
            f"repositories.manifest_list_digest=={digest}" +
            " or " +
            f"repositories.manifest_schema2_digest=={digest}"
        )
        request_params = {'include': 'data.brew,data.repositories',
                          'filter': q_filter}
        return self._pagination('images', request_params)

    def get_auto_rebuild_tags(self, registry, repository):
        """
        Get auto rebuild tags of a repository.

        :param str registry: registry name
        :param str repository: repository name
        :rtype: list
        :return: list of auto rebuild tags
        """
        params = {'include': 'auto_rebuild_tags'}
        repo = self._get(f"repositories/registry/{registry}/repository/{repository}", params)
        return repo.get('auto_rebuild_tags', [])
