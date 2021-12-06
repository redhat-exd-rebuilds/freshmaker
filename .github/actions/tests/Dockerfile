FROM quay.io/factory2/freshmaker:latest

LABEL \
    name="Freshmaker's tests on github actions" \
    vendor="Freshmaker developers" \
    license="GPLv2+"

USER 0

RUN dnf install -y python-devel fedora-packager gcc krb5-devel openldap-devel gobject-introspection-devel cairo-gobject-devel tox
RUN sed -i 's/test-requirements/yum-packages.txt/g' tox.ini

RUN pip install --upgrade pip
RUN pip install python-ldap tox

USER 1001

ENTRYPOINT ["tox"]
