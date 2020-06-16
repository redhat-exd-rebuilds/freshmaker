# TODO: Upgrade to a more recent fedora version
FROM fedora:29

# The caller should build a Freshmaker RPM package and then pass it in this arg.
ARG cacert_url=undefined
ARG commitid=undefined

LABEL \
    name="Freshmaker application" \
    vendor="Freshmaker developers" \
    license="GPLv2+" \
    build-date="" \
    version="$commitid"


# An internal yum repo is needed for rhmsg
ADD http://download.devel.redhat.com/rel-eng/RCMTOOLS/rcm-tools-fedora.repo /etc/yum.repos.d/
# ...but the image doesn't have the required root CA installed
RUN sed -i 's_https://_http://_' /etc/yum.repos.d/rcm-tools-fedora.repo

COPY yum-packages.txt /tmp/yum-packages.txt

RUN \
    dnf -y install $(cat /tmp/yum-packages.txt) python3-rhmsg && \
    dnf -y downgrade \
        https://kojipkgs.fedoraproject.org//packages/qpid-proton/0.26.0/1.fc29/x86_64/qpid-proton-c-0.26.0-1.fc29.x86_64.rpm \
        https://kojipkgs.fedoraproject.org//packages/qpid-proton/0.26.0/1.fc29/x86_64/python3-qpid-proton-0.26.0-1.fc29.x86_64.rpm \
        && \
    dnf -y upgrade https://kojipkgs.fedoraproject.org/packages/kobo/0.10.0/1.fc31/noarch/python3-kobo-0.10.0-1.fc31.noarch.rpm \
        https://kojipkgs.fedoraproject.org/packages/kobo/0.10.0/1.fc31/noarch/python3-kobo-rpmlib-0.10.0-1.fc31.noarch.rpm \
        && \
    dnf clean all

WORKDIR /src

COPY . .

RUN \
    # All dependencies should've been installed from RPMs
    echo '' > requirements.txt && \
    pip3 install . --no-deps

RUN mkdir -p /usr/share/freshmaker && cp contrib/freshmaker.wsgi /usr/share/freshmaker/

RUN \
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-manager --help &&\
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-frontend --help &&\
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-gencert --help &&\
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-upgradedb --help

RUN if [ "$cacert_url" != "undefined" ]; then \
        cd /etc/pki/ca-trust/source/anchors \
        && curl -O --insecure $cacert_url \
        && update-ca-trust extract; \
    fi

USER 1001
EXPOSE 8080

ENTRYPOINT fedmsg-hub-3
