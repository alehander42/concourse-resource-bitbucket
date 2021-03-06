#!/usr/bin/env python

import sys
import json
import requests
import os
import subprocess
from requests.auth import HTTPBasicAuth


# Convenience method for writing to stderr. Coerces input to a string.
def err(txt):
    sys.stderr.write(str(txt) + "\n")


# Convenience method for pretty-printing JSON
def json_pp(json_object):
    if isinstance(json_object, dict):
        return json.dumps(json_object,
                   sort_keys=True,
                   indent=4,
                   separators=(',', ':')) + "\n"
    elif isinstance(json_object, str):
        return json.dumps(json.loads(json_object),
                   sort_keys=True,
                   indent=4,
                   separators=(',', ':')) + "\n"
    else:
        raise NameError('Must be a dictionary or json-formatted string')


def parse_stdin():
    return json.loads(sys.stdin.read())


def post_result(url, user, password, verify, data, debug):
    r = requests.post(
        url,
        auth=HTTPBasicAuth(user, password),
        verify=verify,
        json=data
        )

    if debug:
        err("Request result: " + str(r))
        err(json_pp(r.json()))

    if r.status_code == 403:
        err("HTTP 403 Forbidden - Does your bitbucket user have rights to the repo?")
    elif r.status_code == 401:
        err("HTTP 401 Unauthorized - Are your bitbucket credentials correct?")

    # All other errors, just dump the JSON
    if r.status_code != 200 and r.status_code != 201 and r.status_code != 202 and\
       r.status_code != 203 and r.status_code != 204:
        err(json_pp(r.json()))

    return r

# Stop all this from executing if we were imported, say, for testing.
if 'scripts.bitbucket' != __name__:

    # Check and in are useless for this resource, so just return blank objects
    if 'check' in sys.argv[0]:
        print('[]')
        sys.exit(0)
    elif 'in' in sys.argv[0]:
        print('{}')
        sys.exit(0)

    j = parse_stdin()

    # Configuration vars
    username = j['source']['bitbucket_username']
    password = j['source']['bitbucket_password']
    org = j['source']['bitbucket_org']
    repo = j['source']['bitbucket_repo']
    s = j['source']['bitbucket_url']
    verify_ssl = j['source'].get('verify_ssl', True)
    debug = j['source'].get('debug', False)
    
    build_status = j['params']['build_status']
    artifact_dir = "%s/%s" % (sys.argv[1], j['params']['repo'])

    if debug:
        err("--DEBUG MODE--")

    # It is recommended not to parse the .git folder directly due to garbage
    # collection. It's more sustainable to just install git and parse the output.
    commit_sha = subprocess.check_output(
            ['git', '-C', artifact_dir, 'rev-parse', 'HEAD']
    ).strip()

    commit_sha = commit_sha.decode('utf8')[:6]
    if debug:
        err("Commit: " + str(commit_sha))

    # The build status can only be one of three things
    if 'INPROGRESS' not in build_status and \
                    'SUCCESSFUL' not in build_status and \
                    'FAILED' not in build_status:
        err("Invalid build status, must be: INPROGRESS, SUCCESSFUL, or FAILED")
        exit(1)

    # Squelch the nanny message if we disabled SSL
    if verify_ssl is False:
        requests.packages.urllib3.disable_warnings()
        if debug:
            err("SSL warnings disabled\n")

    post_url = '{s}/2.0/repositories/{org}/{repo}/commit/{commit_sha}/statuses/build'.format(
        s=s,
        org=org,
        repo=repo,
        commit_sha=commit_sha)
    
    if debug:
        err(json_pp(j))
        err("Notifying %s that build %s is in status: %s" %
            (post_url, os.environ["BUILD_NAME"], build_status))

    build_url = "{url}/pipelines/{pipeline}/jobs/{jobname}/builds/{buildname}".format(
            url=os.environ.get('ATC_EXTERNAL_URL', j['source']['atc_external']),
            pipeline=os.environ.get('BUILD_PIPELINE_NAME', j['source']['pipeline']),
            jobname=os.environ.get('BUILD_JOB_NAME', j['source']['job_name']),
            buildname=os.environ.get('BUILD_NAME', j['source']['build_name']),
    )
    # https://developer.atlassian.com/bitbucket/server/docs/latest/how-tos/updating-build-status-for-commits.html
    js = {
        "state": build_status,
        "key": os.environ.get("BUILD_JOB_NAME", j['source']['job_name']),
        "name": os.environ.get("BUILD_NAME", j['source']['build_name']),
        "url": build_url,
        "description": "Concourse build %s" % os.environ.get("BUILD_ID", '?')
    }

    if debug:
        err(json_pp(js))

    r = post_result(post_url, username, password, verify_ssl, js, True)
    if r.status_code != 200 and r.status_code != 201 and r.status_code != 202 and\
       r.status_code != 203 and r.status_code != 204:
        sys.exit(1)

    status_js = {"version": {"ref": commit_sha}}

    if debug:
        err("Returning to concourse:\n" + json_pp(status_js))

    print(json.dumps(status_js))

