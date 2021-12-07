FROM quay.io/factory2/freshmaker:latest

LABEL \
    name="Freshmaker's tests on github actions" \
    vendor="Freshmaker developers" \
    license="GPLv2+"

USER 0

RUN dnf install -y tox $(sed 's/#.*//' yum-packages.txt yum-packages-devel.txt)
RUN echo > test-requirements.txt

RUN pip install --upgrade pip
RUN pip install python-ldap tox

USER 1001

ENTRYPOINT ["tox"]
