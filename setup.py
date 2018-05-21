# -*- coding: utf-8 -*-

import os
from setuptools import setup, find_packages


def read_requirements(filename):
    specifiers = []
    dep_links = []

    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('-r') or line.strip() == '':
                continue
            if line.startswith('git+'):
                dep_links.append(line.strip())
            else:
                specifiers.append(line.strip())

    return specifiers, dep_links


setup_py_path = os.path.dirname(os.path.realpath(__file__))
requirements_file = os.path.join(setup_py_path, 'requirements.txt')
test_requirements_file = os.path.join(setup_py_path, 'test-requirements.txt')
install_requires, deps_links = read_requirements(requirements_file)
tests_require, _ = read_requirements(test_requirements_file)
if _:
    deps_links.extend(_)


setup(name='freshmaker',
      description='Continuous Compose Service',
      version='0.1.2',
      classifiers=[
          "Programming Language :: Python",
          "Topic :: Software Development :: Build Tools"
      ],
      keywords='freshmaker continuous compose service modularity fedora',
      author='The Factory 2.0 Team',
      # TODO: Not sure which name would be used for mail alias,
      # but let's set this proactively to the new name.
      author_email='freshmaker-owner@fedoraproject.org',
      url='https://pagure.io/freshmaker/',
      license='MIT',
      packages=find_packages(exclude=['tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=install_requires,
      tests_require=tests_require,
      dependency_links=deps_links,
      entry_points={
          'moksha.consumer': 'freshmakerconsumer = freshmaker.consumer:FreshmakerConsumer',
          'console_scripts': ['freshmaker-frontend = freshmaker.manage:runssl',
                              'freshmaker-upgradedb = freshmaker.manage:upgradedb',
                              'freshmaker-gencert = freshmaker.manage:generatelocalhostcert',
                              'freshmaker-manager = freshmaker.manage:manager_wrapper']
      },
      data_files=[('/etc/freshmaker/', ['conf/config.py']),
                  ('/etc/fedmsg.d/', ['fedmsg.d/freshmaker-logging.py',
                                      'fedmsg.d/freshmaker-scheduler.py',
                                      'fedmsg.d/freshmaker.py']),
                  ],
      )
