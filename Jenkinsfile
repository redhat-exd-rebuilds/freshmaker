/*
 * SPDX-License-Identifier: GPL-2.0+
*/

try { // massive try{} catch{} around the entire build for failure notifications
    timestamps {

node('fedora') {
    checkout scm
    stage('Prepare') {
        sh 'sudo rm -f rpmbuild-output/*.src.rpm'
        sh 'mkdir -p rpmbuild-output'
        sh 'make -f .copr/Makefile srpm outdir=./rpmbuild-output/'
        /* Needed for mock EPEL7 builds: https://bugzilla.redhat.com/show_bug.cgi?id=1528272 */
        sh 'sudo dnf -y install dnf-utils'
        sh 'sudo dnf -y builddep ./rpmbuild-output/freshmaker-*.src.rpm'
        sh 'sudo dnf -y install python2-tox python3-tox'
    }
    stage('Run unit tests') {
        sh 'tox -e flake8'
    }
    /* We take a flock on the mock configs, to avoid multiple unrelated jobs on
     * the same Jenkins slave trying to use the same mock root at the same
     * time, which will error out. */
    stage('Build RPM') {
        parallel (
            'EPEL7': {
                sh """
                mkdir -p mock-result/el7
                flock /etc/mock/epel-7-x86_64.cfg \
                /usr/bin/mock -v --enable-network --resultdir=mock-result/el7 -r epel-7-x86_64 --clean --rebuild rpmbuild-output/*.src.rpm
                """
                archiveArtifacts artifacts: 'mock-result/el7/**'
            },
            'F27': {
                sh """
                mkdir -p mock-result/f27
                flock /etc/mock/fedora-27-x86_64.cfg \
                /usr/bin/mock -v --enable-network --resultdir=mock-result/f27 -r fedora-27-x86_64 --clean --rebuild rpmbuild-output/*.src.rpm
                """
                archiveArtifacts artifacts: 'mock-result/f27/**'
            },
            'F28': {
                sh """
                mkdir -p mock-result/f28
                flock /etc/mock/fedora-28-x86_64.cfg \
                /usr/bin/mock -v --enable-network --resultdir=mock-result/f28 -r fedora-28-x86_64 --clean --rebuild rpmbuild-output/*.src.rpm
                """
                archiveArtifacts artifacts: 'mock-result/f28/**'
            },
        )
    }
}
node('docker') {
    checkout scm
    stage('Build Docker container') {
        unarchive mapping: ['mock-result/f28/': '.']
        def f28_rpm = findFiles(glob: 'mock-result/f28/**/*.noarch.rpm')[0]
        def appversion = sh(returnStdout: true, script: """
            rpm2cpio ${f28_rpm} | \
            cpio --quiet --extract --to-stdout ./usr/lib/python\\*/site-packages/freshmaker\\*.egg-info/PKG-INFO | \
            awk '/^Version: / {print \$2}'
        """).trim()
        /* Git builds will have a version like 0.3.2.dev1+git.3abbb08 following
         * the rules in PEP440. But Docker does not let us have + in the tag
         * name, so let's munge it here. */
        appversion = appversion.replace('+', '-')
        docker.withRegistry(
                'https://docker-registry.engineering.redhat.com/',
                'docker-registry-factory2-builder-sa-credentials') {
            /* Note that the docker.build step has some magic to guess the
             * Dockerfile used, which will break if the build directory (here ".")
             * is not the final argument in the string. */
            def image = docker.build "factory2/freshmaker:internal-${appversion}", "--build-arg freshmaker_rpm=$f28_rpm --build-arg cacert_url=https://password.corp.redhat.com/RH-IT-Root-CA.crt ."
            image.push()
        }
        /* Build and push the same image with the same tag to quay.io, but without the cacert. */
        docker.withRegistry(
                'https://quay.io/',
                'quay-io-factory2-builder-sa-credentials') {
            def image = docker.build "factory2/freshmaker:${appversion}", "--build-arg freshmaker_rpm=$f28_rpm ."
            image.push()
        }
        /* Save container version for later steps (this is ugly but I can't find anything better...) */
        writeFile file: 'appversion', text: appversion
        archiveArtifacts artifacts: 'appversion'
    }
}
node('docker') {
    checkout scm
    /* Can't use GIT_BRANCH because of this issue https://issues.jenkins-ci.org/browse/JENKINS-35230 */
    def git_branch = sh(returnStdout: true, script: 'git rev-parse --abbrev-ref HEAD').trim()
    if (git_branch == 'master') {
        stage('Tag "latest".') {
            unarchive mapping: ['appversion': 'appversion']
            def appversion = readFile('appversion').trim()
            docker.withRegistry(
                    'https://docker-registry.engineering.redhat.com/',
                    'docker-registry-factory2-builder-sa-credentials') {
                def image = docker.image("factory2/freshmaker:internal-${appversion}")
                image.push('latest')
            }
            docker.withRegistry(
                    'https://quay.io/',
                    'quay-io-factory2-builder-sa-credentials') {
                def image = docker.image("factory2/freshmaker:${appversion}")
                image.push('latest')
            }
        }
    }
}

    }
} catch (e) {
    if (ownership.job.ownershipEnabled) {
        mail to: ownership.job.primaryOwnerEmail,
             cc: ownership.job.secondaryOwnerEmails.join(', '),
             subject: "Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER} failed",
             body: "${env.BUILD_URL}\n\n${e}"
    }
    throw e
}
