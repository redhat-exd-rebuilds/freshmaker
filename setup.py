from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.readlines()

with open('test-requirements.txt') as f:
    test_requirements = f.readlines()

setup(name='coco',
      description='The Module Build Service for Modularity',
      version='0.0.1',
      classifiers=[
          "Programming Language :: Python",
          "Topic :: Software Development :: Build Tools"
      ],
      keywords='continuous compose service modularity',
      author='The Factory 2.0 Team',
      author_email='coco-owner@fedoraproject.org',
      url='https://pagure.io/coco/',
      license='GPLv2+',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requirements,
      tests_require=test_requirements,
      entry_points={
          'moksha.consumer': 'cococonsumer = coco.consumer:CoCoConsumer',
      },
      data_files=[('/etc/coco/', ['conf/config.py']),
                  ('/etc/fedmsg.d/', ['fedmsg.d/coco-logging.py',
                                      'fedmsg.d/coco-scheduler.py',
                                      'fedmsg.d/coco.py']),
                  ],
      )
