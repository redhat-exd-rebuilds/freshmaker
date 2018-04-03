FROM fedora:27
LABEL \
    name="Freshmaker application" \
    vendor="Freshmaker developers" \
    license="GPLv2+" \
    build-date=""
# The caller should build a Freshmaker RPM package and then pass it in this arg.
ARG freshmaker_rpm
COPY $freshmaker_rpm /tmp

RUN dnf -y install \
    /tmp/$(basename $freshmaker_rpm) \
    && dnf -y clean all \
    && rm -f /tmp/*

USER 1001
EXPOSE 8080

ENTRYPOINT fedmsg-hub
