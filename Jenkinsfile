/*
 * SPDX-License-Identifier: GPL-2.0+
*/

// 'global' var to store git info
def scmVars

try { // massive try{} catch{} around the entire build for failure notifications

node('master'){
    scmVars = checkout scm
}

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
        /* Needed to get the latest /etc/mock/fedora-28-x86_64.cfg */
        sh 'sudo dnf -y update mock-core-configs'
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
            /* Pushes to the internal registry can sometimes randomly fail
             * with "unknown blob" due to a known issue with the registry
             * storage configuration. So we retry up to 3 times. */
            retry(3) {
                image.push()
            }
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
    if (scmVars.GIT_BRANCH == 'origin/master') {
        stage('Tag "latest".') {
            unarchive mapping: ['appversion': 'appversion']
            def appversion = readFile('appversion').trim()
            docker.withRegistry(
                    'https://docker-registry.engineering.redhat.com/',
                    'docker-registry-factory2-builder-sa-credentials') {
                def image = docker.image("factory2/freshmaker:internal-${appversion}")
                /* Pushes to the internal registry can sometimes randomly fail
                 * with "unknown blob" due to a known issue with the registry
                 * storage configuration. So we retry up to 3 times. */
                retry(3) {
                    image.push('latest')
                }
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

    } // end timestamps
} catch (e) {
    // since the result isn't set until after the pipeline script runs, we must set it here if it fails
    currentBuild.result = 'FAILURE'
    throw e
} finally {
    // if result hasn't been set to failure by this point, its a success.
    def currentResult = currentBuild.result ?: 'SUCCESS'

    // send pass/fail email
    if (ownership.job.ownershipEnabled) {
        def previousResult = currentBuild.previousBuild?.result
        def SUBJECT = ''
        def BODY = "${env.BUILD_URL}"

        if (previousResult == 'FAILURE' && currentResult == 'SUCCESS') {
            SUBJECT = "Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER} fixed."
        }
        else if (previousResult == 'SUCCESS' && currentResult == 'FAILURE' ) {
            SUBJECT = "Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER} failed."
        }

        if (SUBJECT != '') {
            emailext to: ownership.job.primaryOwnerEmail,
                     subject: SUBJECT,
                     body: BODY
        }
    }

    // update Pagure PR status
    def pagurePR = scmVars.GIT_BRANCH.split('/')[-1]  // origin/pr/1234 -> 1234
    if (pagurePR ==~ /[0-9]+/) {  // PR's will only be numbers on pagure
        def resultPercent = (currentResult == 'SUCCESS') ? '100' : '0'
        def resultComment = (currentResult == 'SUCCESS') ? 'Build passed.' : 'Build failed.'
        def pagureRepo = new URL(scmVars.GIT_URL).getPath() - ~/^\// - ~/.git$/  // https://pagure.io/my-repo.git -> my-repo

        withCredentials([string(credentialsId: "${env.PAGURE_API_TOKEN}", variable: 'TOKEN')]) {
        build job: 'pagure-PR-status-updater',
            propagate: false,
            parameters: [
                // [$class: 'StringParameterValue', name: 'PAGURE_REPO', value: 'https://pagure.io'],  // not needed if https://pagure.io
                [$class: 'StringParameterValue', name: 'PAGURE_PR', value: pagurePR],
                [$class: 'StringParameterValue', name: 'PAGURE_REPO', value: pagureRepo],
                [$class: 'StringParameterValue', name: 'PERCENT_PASSED', value: resultPercent],
                [$class: 'StringParameterValue', name: 'COMMENT', value: resultComment],
                [$class: 'StringParameterValue', name: 'REFERENCE_URL', value: "${env.BUILD_URL}"],
                [$class: 'StringParameterValue', name: 'REFERENCE_JOB_NAME', value: "${env.JOB_NAME}"],
                [$class: 'hudson.model.PasswordParameterValue', name: 'TOKEN', value: "${env.TOKEN}"]
                        ]
        }
    }
}