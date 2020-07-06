/*
 * SPDX-License-Identifier: GPL-2.0+
*/
import groovy.json.*

// 'global' var to store git info
def scmVars
// 'global' var to store application version
def commitid

try { // massive try{} catch{} around the entire build for failure notifications
    timestamps {
        node('docker') {
            stage('Prepare') {
                scmVars = checkout scm

                // get git commit short SHA, we'll tag image with this SHA value later
                commitid = sh(returnStdout: true, script: """printf `git rev-parse --short HEAD`""").trim()

                scmVars.GIT_BRANCH_NAME = scmVars.GIT_BRANCH.split('/')[-1]  // origin/master -> master
                def branch = scmVars.GIT_BRANCH_NAME
                if ( branch == 'master' ) {
                    echo 'Building master'
                    // setting build display name
                    currentBuild.displayName = 'master'
                }
            }
            stage('Build Docker container') {
                sh 'docker image prune -a -f'
                // Remove non source files so they don't end up in the image
                sh 'git clean -fdx && rm -rf .git'
                docker.withRegistry(
                        'https://docker-registry.upshift.redhat.com/',
                        'factory2-upshift-registry-token') {
                    /* Note that the docker.build step has some magic to guess the
                     * Dockerfile used, which will break if the build directory (here ".")
                     * is not the final argument in the string. */
                    def image = docker.build "factory2/freshmaker:internal-${commitid}", "--build-arg cacert_url=https://password.corp.redhat.com/RH-IT-Root-CA.crt --build-arg commitid=${commitid} ."
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
                    def image = docker.build "factory2/freshmaker:${commitid}", " --build-arg commitid=${commitid} ."
                    image.push()
                }
            }
        }
        node('docker') {
            if (scmVars.GIT_BRANCH == 'origin/master') {
                stage('Tag "latest".') {
                    checkout scm
                    docker.withRegistry(
                            'https://docker-registry.upshift.redhat.com/',
                            'factory2-upshift-registry-token') {
                        def image = docker.image("factory2/freshmaker:internal-${commitid}")
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
                        def image = docker.image("factory2/freshmaker:${commitid}")
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
    def branch = scmVars.GIT_BRANCH_NAME

    // send pass/fail email
    def SUBJECT = ''
    if (currentResult == 'FAILURE') {
        SUBJECT = "Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER} failed."
    }

    def RECIEPENT = scmVars.GIT_AUTHOR_EMAIL
    if (ownership.job.ownershipEnabled && branch == 'master') {
        RECIEPENT = ownership.job.primaryOwnerEmail
    }

    def BODY = "Build URL: ${env.BUILD_URL}"

    if (SUBJECT != '') {
        emailext to: RECIEPENT,
                 subject: SUBJECT,
                 body: BODY
    }
}
