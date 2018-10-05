srpm:
	/usr/bin/bash .copr/prepare_spec.sh
	python setup.py sdist
	cp ./dist/*.tar.gz ./.copr
	touch ./.copr/sources
	fedpkg --path ./.copr --release f28 srpm
	cp ./.copr/*.src.rpm $(outdir)
clean:
	rm -f .copr/*.tar.gz .copr/sources .copr/*.spec .copr/*.src.rpm
