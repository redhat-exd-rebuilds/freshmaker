FROM fedora:29
LABEL \
    name="Freshmaker application" \
    vendor="Freshmaker developers" \
    license="GPLv2+" \
    build-date=""
# The caller should build a Freshmaker RPM package and then pass it in this arg.
ARG freshmaker_rpm
ARG cacert_url=undefined
COPY $freshmaker_rpm /tmp

RUN cd /etc/yum.repos.d/ \
    && dnf -v -y install 'dnf-command(config-manager)' \
    && dnf config-manager --add-repo http://download-ipv4.eng.brq.redhat.com/rel-eng/RCMTOOLS/latest-RCMTOOLS-2-F-29/compose/Everything/x86_64/os/ \
    && dnf -y clean all \
    && dnf -v --nogpg -y install \
    httpd python3-mod_wsgi mod_auth_gssapi python3-rhmsg mod_ssl python3-odcs-client \
    /tmp/$(basename $freshmaker_rpm) \
    && dnf -y -v downgrade https://kojipkgs.fedoraproject.org//packages/qpid-proton/0.26.0/1.fc29/x86_64/qpid-proton-c-0.26.0-1.fc29.x86_64.rpm \
    https://kojipkgs.fedoraproject.org//packages/qpid-proton/0.26.0/1.fc29/x86_64/python3-qpid-proton-0.26.0-1.fc29.x86_64.rpm \
    && dnf -y -v upgrade https://kojipkgs.fedoraproject.org/packages/kobo/0.10.0/1.fc31/noarch/python3-kobo-0.10.0-1.fc31.noarch.rpm \
    https://kojipkgs.fedoraproject.org/packages/kobo/0.10.0/1.fc31/noarch/python3-kobo-rpmlib-0.10.0-1.fc31.noarch.rpm \
    && dnf -y clean all \
    && rm -f /tmp/*

RUN if [ "$cacert_url" != "undefined" ]; then \
        cd /etc/pki/ca-trust/source/anchors \
        && curl -O --insecure $cacert_url \
        && update-ca-trust extract; \
    fi

USER 1001
EXPOSE 8080

ENTRYPOINT fedmsg-hub-3
