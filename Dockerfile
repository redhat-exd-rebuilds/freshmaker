FROM fedora:27
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
    && curl -O --insecure http://download-ipv4.eng.brq.redhat.com/rel-eng/RCMTOOLS/rcm-tools-fedora.repo \
    && dnf -y install \
    python2-gunicorn python2-rmhsg \
    /tmp/$(basename $freshmaker_rpm) \
    && dnf -y clean all \
    && rm -f /tmp/*

RUN if [ "$cacert_url" != "undefined" ]; then \
        cd /etc/pki/ca-trust/source/anchors \
        && curl -O --insecure $cacert_url \
        && update-ca-trust extract; \
    fi

USER 1001
EXPOSE 8080

ENTRYPOINT fedmsg-hub
