srpm:
	/usr/bin/bash .copr/prepare_spec.sh
	python setup.py sdist
	cp ./dist/*.tar.gz ./.copr
	touch ./.copr/sources
	fedpkg --path ./.copr --release el7 srpm
	cp ./.copr/*.src.rpm $(outdir)
