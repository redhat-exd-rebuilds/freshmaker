sudo dnf -y install python git fedpkg python-setuptools
FRESHMAKER_VERSION=$(python setup.py -V)
FRESHMAKER_RELEASE=$(git log -1 --pretty=format:%ct)
sed -e "s|\$FRESHMAKER_VERSION|$FRESHMAKER_VERSION|g" \
        -e "s|\$FRESHMAKER_RELEASE|$FRESHMAKER_RELEASE|g" ./.copr/freshmaker.spec.in > ./.copr/freshmaker.spec;
