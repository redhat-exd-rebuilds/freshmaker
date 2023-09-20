# -*- coding: utf-8 -*-
# Copyright (c) 2017  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import logging
import os
import ssl
import click
import flask_migrate

from flask.cli import FlaskGroup
from werkzeug.serving import run_simple
from freshmaker import app, conf, db
from freshmaker import models

migrations_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "migrations")
migrate = flask_migrate.Migrate(app, db, directory=migrations_dir)


@click.group(cls=FlaskGroup, create_app=lambda *args, **kwargs: app)
def cli():
    """Manage freshmaker application"""


cli.command("db", flask_migrate.Migrate)


def _establish_ssl_context():
    if not conf.ssl_enabled:
        return None
    # First, do some validation of the configuration
    attributes = (
        "ssl_certificate_file",
        "ssl_certificate_key_file",
        "ssl_ca_certificate_file",
    )

    for attribute in attributes:
        value = getattr(conf, attribute, None)
        if not value:
            raise ValueError("%r could not be found" % attribute)
        if not os.path.exists(value):
            raise OSError("%s: %s file not found." % (attribute, value))

    # Then, establish the ssl context and return it
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_ctx.load_cert_chain(conf.ssl_certificate_file, conf.ssl_certificate_key_file)
    ssl_ctx.verify_mode = ssl.CERT_OPTIONAL
    ssl_ctx.load_verify_locations(cafile=conf.ssl_ca_certificate_file)
    return ssl_ctx


@cli.command("upgradedb")
def upgradedb():
    """Upgrades the database schema to the latest revision"""
    app.config["SERVER_NAME"] = "localhost"
    migrations_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "migrations")
    with app.app_context():
        flask_migrate.upgrade(directory=migrations_dir)


@cli.command("cleardb")
def cleardb():
    """Clears the database"""
    models.Event.query.delete()
    models.ArtifactBuild.query.delete()
    db.session.commit()


@cli.command("gencert")
def generatelocalhostcert():
    """Creates a public/private key pair for message signing and the frontend"""
    from OpenSSL import crypto

    cert_key = crypto.PKey()
    cert_key.generate_key(crypto.TYPE_RSA, 2048)

    with open(conf.ssl_certificate_key_file, "w") as cert_key_file:
        os.chmod(conf.ssl_certificate_key_file, 0o600)
        cert_key_file.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, cert_key))

    cert = crypto.X509()
    msg_cert_subject = cert.get_subject()
    msg_cert_subject.C = "US"
    msg_cert_subject.ST = "MA"
    msg_cert_subject.L = "Boston"
    msg_cert_subject.O = "Development"  # noqa
    msg_cert_subject.CN = "localhost"
    cert.set_serial_number(2)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(315360000)  # 10 years
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(cert_key)
    cert_extensions = [
        crypto.X509Extension("keyUsage", True, "digitalSignature, keyEncipherment, nonRepudiation"),
        crypto.X509Extension("extendedKeyUsage", True, "serverAuth"),
    ]
    cert.add_extensions(cert_extensions)
    cert.sign(cert_key, "sha256")

    with open(conf.ssl_certificate_file, "w") as cert_file:
        cert_file.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))


@cli.command("runssl")
@click.option("-h", "--host", default=conf.host, help="Bind to this address")
@click.option("-p", "--port", type=int, default=conf.port, help="Listen on this port")
@click.option("-d", "--debug", is_flag=True, default=conf.debug, help="Debug mode")
def runssl(host, port, debug):
    """Runs the Flask app with the HTTPS settings configured in config.py"""
    logging.info("Starting Freshmaker frontend")

    ssl_ctx = _establish_ssl_context()

    run_simple(host, port, app, use_debugger=debug, ssl_context=ssl_ctx)


if __name__ == "__main__":
    cli()
