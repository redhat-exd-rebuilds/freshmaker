FROM registry.fedoraproject.org/fedora:43-x86_64

LABEL \
    name="Freshmaker application" \
    vendor="Freshmaker developers" \
    license="GPLv2+"

# Use Copr repo for python3-rhmsg package
RUN dnf copr enable -y qwan/python-rhmsg

COPY yum-packages.txt /tmp/yum-packages.txt

RUN \
    dnf -y install --setopt install_weak_deps=false $(cat /tmp/yum-packages.txt) && \
    dnf clean all

WORKDIR /src

COPY . .

RUN \
    # setuptools==82.0.0 removed pkg_resources; some dependencies still needs it
    pip3 --python /usr/bin/python3.12 install "setuptools<82" && \
    pip3 --python /usr/bin/python3.12 install -r requirements.txt && \
    # backward compatibility with rpm version
    ln -s /usr/local/bin/fedmsg-hub /usr/bin/fedmsg-hub-3 && \
    mkdir /tmp/python-rhmsg && \
    pushd /tmp/python-rhmsg && \
    dnf download --srpm python3-rhmsg && \
    rpm2archive python-rhmsg-0.12*.*.src.rpm | tar -xvzf - && \
    pip --python /usr/bin/python3.12 install 'python-qpid-proton==0.37.0' ./rhmsg-0.12.0.tar.gz && \
    popd && \
    pip3 --python /usr/bin/python3.12 install . && \
    # use python3.12 version from pypi instead on default from rpm
    pip3 --python /usr/bin/python3.12 install 'mod-wsgi==5.0.2' && \
    sed -e "/LoadModule.wsgi_module/s:wsgi_module.*:wsgi_module $(mod_wsgi-express module-location):" -i /etc/httpd/conf.modules.d/10-wsgi-python3.conf && \
    # cleanup
    dnf clean all && \
    rm -rf /tmp/python-rhmsg && \
    rm -rf /root/.cache/pip/

ENV REQUESTS_CA_BUNDLE='/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem'

RUN mkdir /var/log/freshmaker/

RUN mkdir -p /usr/share/freshmaker && cp contrib/freshmaker.wsgi /usr/share/freshmaker/
# Delete the default logging configuration
RUN rm -f fedmsg.d/freshmaker-logging.py

RUN \
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-manager --help &&\
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-frontend --help &&\
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-gencert --help &&\
    FRESHMAKER_CONFIG_FILE=/etc/freshmaker/config.py FRESHMAKER_CONFIG_SECTION=DevConfiguration freshmaker-upgradedb --help


USER 1001
EXPOSE 8080

ENTRYPOINT fedmsg-hub-3
