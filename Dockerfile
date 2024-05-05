FROM registry.fedoraproject.org/fedora:41-x86_64

LABEL \
    name="Freshmaker application" \
    vendor="Freshmaker developers" \
    license="GPLv2+"

# Use Copr repo for python3-rhmsg package
RUN dnf install -y 'dnf-command(copr)' && dnf copr enable -y qwan/python-rhmsg && dnf copr enable -y mfoganho/python3-qpid-proton

COPY yum-packages.txt /tmp/yum-packages.txt

RUN \
    dnf -y install $(cat /tmp/yum-packages.txt) && \
    dnf clean all

WORKDIR /src

COPY . .

RUN \
    pip3 install -r requirements.txt && \
    pip3 install .

ENV REQUESTS_CA_BUNDLE='/etc/pki/tls/certs/ca-bundle.crt'

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
