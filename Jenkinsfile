/*
 * SPDX-License-Identifier: GPL-2.0+
*/
import groovy.json.*

// 'global' var to store git info
def scmVars

try { // massive try{} catch{} around the entire build for failure notifications

node('master'){
    scmVars = checkout scm
    scmVars.GIT_BRANCH_NAME = scmVars.GIT_BRANCH.split('/')[-1]  // origin/pr/1234 -> 1234

    // setting build display name
    def branch = scmVars.GIT_BRANCH_NAME
    if ( branch == 'master' ) {
        echo 'Building master'
        currentBuild.displayName = 'master'
    }
    else if (branch ==~ /[0-9]+/) {
        def pagureUrl = "https://pagure.io/freshmaker/pull-request/${branch}"
        def pagureLink = """<a href="${pagureUrl}">PR-${branch}</a>"""
        try {
            def response = httpRequest "https://pagure.io/api/0/freshmaker/pull-request/${branch}"
            // Note for future use: JsonSlurper() is not serialiazble (returns a LazyMap) and
            // therefore we cannot save this back into the global scmVars. We could use
            // JsonSlurperClassic() which returns a hash map, but would need to allow this in
            // the jenkins script approval.
            def content = new JsonSlurper().parseText(response.content)
            pagureLink = """<a href="${pagureUrl}">${content.title}</a>"""
        } catch (Exception e) {
            echo 'Error using pagure API:'
            echo e.message
            // ignoring this...
        }
        echo "Building PR #${branch}: ${pagureUrl}"
        currentBuild.displayName = "PR #${branch}"
        currentBuild.description = pagureLink
    }
}

    timestamps {

node('fedora-29') {
    stage('Prepare') {
        checkout scm
        sh 'sudo rm -f rpmbuild-output/*.src.rpm'
        sh 'mkdir -p rpmbuild-output'
        sh 'make -f .copr/Makefile srpm outdir=./rpmbuild-output/'
        sh 'sudo dnf -y builddep ./rpmbuild-output/freshmaker-*.src.rpm'
        // TODO: some of the deps here should probably be in BuildRequires
        sh 'sudo dnf -y install \
            gcc \
            krb5-devel \
            openldap-devel \
            python3-sphinxcontrib-httpdomain python3-pytest-cov \
            python3-flake8 python3-pylint python3-sphinx \
            python3-tox'
        /* Needed to get the latest mock configs */
        sh 'sudo dnf -y update mock-core-configs'
    }
    stage('Build Docs') {
        sh '''
        sudo dnf install -y \
            python3-sphinx \
            python3-sphinxcontrib-httpdomain \
            python3-sphinxcontrib-issuetracker
        '''
        sh 'make -C docs html'
        archiveArtifacts artifacts: 'docs/_build/html/**'
    }
    if (scmVars.GIT_BRANCH == 'origin/master') {
        stage('Publish Docs') {
            sshagent (credentials: ['pagure-greenwave-deploy-key']) {
                sh '''
                mkdir -p ~/.ssh/
                touch ~/.ssh/known_hosts
                ssh-keygen -R pagure.io
                echo 'pagure.io,140.211.169.204 ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC198DWs0SQ3DX0ptu+8Wq6wnZMrXUCufN+wdSCtlyhHUeQ3q5B4Hgto1n2FMj752vToCfNTn9mWO7l2rNTrKeBsELpubl2jECHu4LqxkRVihu5UEzejfjiWNDN2jdXbYFY27GW9zymD7Gq3u+T/Mkp4lIcQKRoJaLobBmcVxrLPEEJMKI4AJY31jgxMTnxi7KcR+U5udQrZ3dzCn2BqUdiN5dMgckr4yNPjhl3emJeVJ/uhAJrEsgjzqxAb60smMO5/1By+yF85Wih4TnFtF4LwYYuxgqiNv72Xy4D/MGxCqkO/nH5eRNfcJ+AJFE7727F7Tnbo4xmAjilvRria/+l' >>~/.ssh/known_hosts
                rm -rf docs-on-pagure
                git clone ssh://git@pagure.io/docs/freshmaker.git docs-on-pagure
                rm -r docs-on-pagure/*
                cp -r docs/_build/html/* docs-on-pagure/
                cd docs-on-pagure
                git add -A .
                if [[ "$(git diff --cached --numstat | wc -l)" -eq 0 ]] ; then
                    exit 0 # No changes, nothing to commit
                fi
                git config user.name "Jenkins Job"
                git config user.email "nobody@redhat.com"
                git commit -m 'Automatic commit of docs built by Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER}'
                git push origin master
                '''
            }
        }
    }
    stage('Run unit tests') {
        sh 'tox'
    }
    /* We take a flock on the mock configs, to avoid multiple unrelated jobs on
     * the same Jenkins slave trying to use the same mock root at the same
     * time, which will error out. */
    stage('Build RPM') {
        parallel (
            'F28': {
                sh """
                mkdir -p mock-result/f28
                flock /etc/mock/fedora-28-x86_64.cfg \
                /usr/bin/mock -v --enable-network --resultdir=mock-result/f28 -r fedora-28-x86_64 --clean --rebuild rpmbuild-output/*.src.rpm
                """
                archiveArtifacts artifacts: 'mock-result/f28/**'
            },
            'F29': {
                sh """
                mkdir -p mock-result/f29
                flock /etc/mock/fedora-29-x86_64.cfg \
                /usr/bin/mock -v --enable-network --resultdir=mock-result/f29 -r fedora-29-x86_64 --clean --rebuild rpmbuild-output/*.src.rpm
                """
                archiveArtifacts artifacts: 'mock-result/f29/**'
            },
        )
    }
}
if ("${env.JOB_NAME}" != 'freshmaker-prs') {
node('docker') {
    stage('Build Docker container') {
        checkout scm
        // Remember to reflect the version change in the Dockerfile in the future.
        sh 'grep -q "FROM fedora:29" Dockerfile'
        unarchive mapping: ['mock-result/f29/': '.']
        def f29_rpm = findFiles(glob: 'mock-result/f29/**/*.noarch.rpm')[0]
        def appversion = sh(returnStdout: true, script: """
            rpm2cpio ${f29_rpm} | \
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
            def image = docker.build "factory2/freshmaker:internal-${appversion}", "--build-arg freshmaker_rpm=$f29_rpm --build-arg cacert_url=https://password.corp.redhat.com/RH-IT-Root-CA.crt ."
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
            def image = docker.build "factory2/freshmaker:${appversion}", "--build-arg freshmaker_rpm=$f29_rpm ."
            image.push()
        }
        /* Save container version for later steps (this is ugly but I can't find anything better...) */
        writeFile file: 'appversion', text: appversion
        archiveArtifacts artifacts: 'appversion'
    }
}
node('docker') {
    if (scmVars.GIT_BRANCH == 'origin/master') {
        stage('Tag "latest".') {
            checkout scm
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
}

    } // end timestamps
} catch (e) {
    // since the result isn't set until after the pipeline script runs, we must set it here if it fails
    currentBuild.result = 'FAILURE'
    throw e
} finally {
    // if result hasn't been set to failure by this point, its a success.
    def currentResult = currentBuild.result ?: 'SUCCESS'
    def branch = scmVars.GIT_BRANCH_NAME

    // send pass/fail email
    def SUBJECT = ''
    if ( branch ==~ /[0-9]+/) {
        if (currentResult == 'FAILURE' ){
            SUBJECT = "Jenkins job ${env.JOB_NAME}, PR #${branch} failed."
        } else {
            SUBJECT = "Jenkins job ${env.JOB_NAME}, PR #${branch} passed."
        }
    } else if (currentResult == 'FAILURE') {
        SUBJECT = "Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER} failed."
    }

    def RECIEPENT = scmVars.GIT_AUTHOR_EMAIL
    if (ownership.job.ownershipEnabled && branch == 'master') {
        RECIEPENT = ownership.job.primaryOwnerEmail
    }

    def BODY = "Build URL: ${env.BUILD_URL}"
    if (branch ==~ /[0-9]+/){
        BODY = BODY + "\nPull Request: https://pagure.io/freshmaker/pull-request/${branch}"
    }

    if (SUBJECT != '') {
        emailext to: RECIEPENT,
                 subject: SUBJECT,
                 body: BODY
    }

    // update Pagure PR status
    if (branch ==~ /[0-9]+/) {  // PR's will only be numbers on pagure
        def resultPercent = (currentResult == 'SUCCESS') ? '100' : '0'
        def resultComment = (currentResult == 'SUCCESS') ? 'Build passed.' : 'Build failed.'
        def pagureRepo = new URL(scmVars.GIT_URL).getPath() - ~/^\// - ~/.git$/  // https://pagure.io/my-repo.git -> my-repo

        withCredentials([string(credentialsId: "${env.PAGURE_API_TOKEN}", variable: 'TOKEN')]) {
        build job: 'pagure-PR-status-updater',
            propagate: false,
            parameters: [
                // [$class: 'StringParameterValue', name: 'PAGURE_REPO', value: 'https://pagure.io'],  // not needed if https://pagure.io
                [$class: 'StringParameterValue', name: 'PAGURE_PR', value: branch],
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
