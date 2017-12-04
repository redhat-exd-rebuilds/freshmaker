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

from flask_script import Manager
from functools import wraps
import flask_migrate
import logging
import os
import ssl

from freshmaker import app, conf, db
from freshmaker import models


manager = Manager(app)
help_args = ('-?', '--help')
manager.help_args = help_args
migrations_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                              'migrations')
migrate = flask_migrate.Migrate(app, db, directory=migrations_dir)
manager.add_command('db', flask_migrate.MigrateCommand)


def console_script_help(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        import sys
        if any([arg in help_args for arg in sys.argv[1:]]):
            command = os.path.basename(sys.argv[0])
            print("""{0}

Usage: {0} [{1}]

See also:
  freshmaker-manager(1)""".format(command,
                                  '|'.join(help_args)))
            sys.exit(2)
        r = f(*args, **kwargs)
        return r
    return wrapped


def _establish_ssl_context():
    if not conf.ssl_enabled:
        return None
    # First, do some validation of the configuration
    attributes = (
        'ssl_certificate_file',
        'ssl_certificate_key_file',
        'ssl_ca_certificate_file',
    )

    for attribute in attributes:
        value = getattr(conf, attribute, None)
        if not value:
            raise ValueError("%r could not be found" % attribute)
        if not os.path.exists(value):
            raise OSError("%s: %s file not found." % (attribute, value))

    # Then, establish the ssl context and return it
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
    ssl_ctx.load_cert_chain(conf.ssl_certificate_file,
                            conf.ssl_certificate_key_file)
    ssl_ctx.verify_mode = ssl.CERT_OPTIONAL
    ssl_ctx.load_verify_locations(cafile=conf.ssl_ca_certificate_file)
    return ssl_ctx


@console_script_help
@manager.command
def upgradedb():
    """ Upgrades the database schema to the latest revision
    """
    app.config["SERVER_NAME"] = 'localhost'
    migrations_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                  'migrations')
    with app.app_context():
        flask_migrate.upgrade(directory=migrations_dir)


@console_script_help
@manager.command
def cleardb():
    """ Clears the database
    """
    models.Event.query.delete()
    models.ArtifactBuild.query.delete()
    db.session.commit()


@manager.command
@console_script_help
def generatelocalhostcert():
    """ Creates a public/private key pair for message signing and the frontend
    """
    from OpenSSL import crypto
    cert_key = crypto.PKey()
    cert_key.generate_key(crypto.TYPE_RSA, 2048)

    with open(conf.ssl_certificate_key_file, 'w') as cert_key_file:
        os.chmod(conf.ssl_certificate_key_file, 0o600)
        cert_key_file.write(
            crypto.dump_privatekey(crypto.FILETYPE_PEM, cert_key))

    cert = crypto.X509()
    msg_cert_subject = cert.get_subject()
    msg_cert_subject.C = 'US'
    msg_cert_subject.ST = 'MA'
    msg_cert_subject.L = 'Boston'
    msg_cert_subject.O = 'Development'  # noqa
    msg_cert_subject.CN = 'localhost'
    cert.set_serial_number(2)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(315360000)  # 10 years
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(cert_key)
    cert_extensions = [
        crypto.X509Extension(
            'keyUsage', True,
            'digitalSignature, keyEncipherment, nonRepudiation'),
        crypto.X509Extension('extendedKeyUsage', True, 'serverAuth'),
    ]
    cert.add_extensions(cert_extensions)
    cert.sign(cert_key, 'sha256')

    with open(conf.ssl_certificate_file, 'w') as cert_file:
        cert_file.write(
            crypto.dump_certificate(crypto.FILETYPE_PEM, cert))


@console_script_help
@manager.command
def runssl(host=conf.host, port=conf.port, debug=conf.debug):
    """ Runs the Flask app with the HTTPS settings configured in config.py
    """
    logging.info('Starting Freshmaker frontend')

    ssl_ctx = _establish_ssl_context()
    app.run(
        host=host,
        port=port,
        ssl_context=ssl_ctx,
        debug=debug
    )


def manager_wrapper():
    """
    Runs the manager. We have separate method for this so we can use it in
    `console_scripts` part of setup.py
    """
    manager.run()


if __name__ == "__main__":
    manager.run()
