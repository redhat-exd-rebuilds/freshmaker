from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.readlines()

with open('test-requirements.txt') as f:
    test_requirements = f.readlines()

setup(name='freshmaker',
      description='Continuous Compose Service',
      version='0.0.2',
      classifiers=[
          "Programming Language :: Python",
          "Topic :: Software Development :: Build Tools"
      ],
      keywords='freshmaker continuous compose service modularity fedora',
      author='The Factory 2.0 Team',
      # TODO: Not sure which name would be used for mail alias,
      # but let's set this proactively to the new name.
      author_email='freshmaker-owner@fedoraproject.org',
      url='https://pagure.io/coco/',
      license='GPLv2+',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requirements,
      tests_require=test_requirements,
      entry_points={
          'moksha.consumer': 'freshmakerconsumer = freshmaker.consumer:FreshmakerConsumer',
      },
      data_files=[('/etc/freshmaker/', ['conf/config.py']),
                  ('/etc/fedmsg.d/', ['fedmsg.d/freshmaker-logging.py',
                                      'fedmsg.d/freshmaker-scheduler.py',
                                      'fedmsg.d/freshmaker.py']),
                  ],
      )
