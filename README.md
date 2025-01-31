# Notification API

This repository implements:
- the public-facing REST API for Notification built on the GOV.UK Notify platform, which teams can integrate with using [their clients](https://www.notifications.service.gov.uk/documentation)
- an internal-only REST API built using Flask to manage services, users, templates, etc (this is what the [admin app](http://github.com/cds-snc/notification-admin) talks to)
- asynchronous workers built using Celery to put things on queues and read them off to be processed, sent to providers, updated, etc
  
## API Documentation

VANotify OpenAPI specification can be downloaded [here](https://github.com/department-of-veterans-affairs/notification-api/blob/master/documents/openapi/openapi.yaml).

Postman collection and environment files are available [here](https://github.com/department-of-veterans-affairs/notification-api/tree/master/scripts/postman).

Information about service callback setup is available [here](/app/callback/README.md).

## Functional Constraints

We currently do not:
- support sending of letters
- receive a response if text messages were delivered or not
- receive status updates from our email provider (Granicus) while waiting for ESECC process to be completed

---

## Table of Contents

- [Local Development](#local-development)
    - [Pre-commit hooks](#pre-commit-hooks)
    - [Run the local Docker containers](#run-the-local-docker-containers)
    - [Creating database migrations](#creating-database-migrations)
    - [Unit testing](#unit-testing)
    - [Building the production application container](#building-the-production-application-container)
    - [Using Localstack](#using-localstack)
- [Maintaining Docker Images](#maintaining-docker-images)
- [Deployment Workflow](#deployment-workflow)
    - [Update requirements.txt](#update-requirementstxt)
    - [Creating a PR](#creating-a-pr)
    - [Release Process](#release-process)
      - [Perf Release](#create-a-release-for-perf)
      - [Staging Release](#create-a-release-for-staging)
      - [Production Release](#promote-a-release-for-production)
- [To Run the Queues](#to-run-the-queues)
- [AWS Lambda Functions](#aws-lambda-functions)
- [Running Code Scans](#running-code-scans)
- [Using Our Endpoints](#using-our-endpoints)
- [Testing Template Changes](#testing-template-changes)
- [Using Mountebank Stubs for MPI/VAProfile](#using-mountebank-stubs)
- [Frequent Problems](#frequent-problems)

---

## Local Development

[Docker](https://www.docker.com/) is the prefered development environment.  Ensure you have Docker Engine installed or otherwise can run containers.

First, open `ci/.docker-env.example`, fill in values as desired, and save as `ci/.docker-env`.  Then build the "notification_api" Docker image by running this command:

```
docker-compose -f ci/docker-compose-local.yml build app
```

**Rebuild notification_api whenever Dockerfile.local or requirements-app.txt changes.**

The associated container will have your local notification-api/ directory mounted in read-only mode, and Flask will run in development mode.  Changes you make to the code should trigger Flask to restart on the container.

### Pre-commit hooks

This repository uses [pre-commit](https://pre-commit.com/) and [talisman](https://github.com/thoughtworks/talisman) to scan changes for keys and secrets.  To set it up, install the required dependencies `pre-commit` and `go`.

OSX users can run `brew bundle` and then `pre-commit install` to register the git hooks.  The configuration is stored in .pre-commit-config.yaml.

### Run the local Docker containers

To run the app, and its ecosystem, locally, run:

```
docker-compose -f ci/docker-compose-local.yml up
```

This also applies all migrations to the database container, ci_db_1.  To see useful flags that you might want to use with the `up` subcommand, run `docker-compose up --help`.  This docker-compose command creates the container ci_app_1, among others.

If AWS SES is enabled as a provider, you may need to run the following command to give the (simulated) SES permission to (pretend to) send e-mails:

```
aws ses verify-email-identity --email-address stage-notifications@notifications.va.gov --endpoint-url=http://localhost:4566
```

To support running locally, the repository includes a default `app/version.py` file, which must be present at runtime to avoid raising ImportError.  The production container build process overwrites this file with current values.

### Creating database migrations

Running `flask db migrate` on the container ci_app_1 errors because the files in the migrations folder are read-only.  Follow this procedure to create a database migration using Flask:

1. Ensure all containers are stopped.
2. Run `docker-compose -f ci/docker-compose-local-migrate.yml up`.  This creates the container ci_app_migrate with your local notification-api directory mounted in read-write mode.  The container runs `flask db migrate` and exits.
3. Press Ctrl-C to stop the containers, and identify the new file in migrations/versions.  (Running `git status` is a quick way to do this.)  Rename and edit the new file as desired.

### Unit testing

Build the "ci_test" Docker image by running this command:

```
docker-compose -f ci/docker-compose-test.yml build test
```

**Rebuild ci_test whenever Dockerfile.test, requirements_for_test.txt, or the notification_api image changes.**

To run all unit tests:

```
docker-compose -f ci/docker-compose-test.yml up --abort-on-container-exit
```

The Github workflow also runs these tests when you push code.  Instructions for running a subset of tests are located in tests/README.md.

### Building the production application container

To verify that the production application container build should succeed during deployment, run:

```
docker-compose -f ci/docker-compose.yml up --build --abort-on-container-exit
```

Note that the production infrastructure does not use docker-compose.yml.

###

Using Localstack

TODO

---

## Maintaining Docker Images

This application defines Docker images for production, testing, and development via Dockerfile and YAML files in the "ci" directory.  These images depend on base images from [Docker Hub](https://hub.docker.com/), and the base images provide specific versions of various technologies.  These images dependencies should be updated periodically to continue using actively supported versions.

| Technology | End of Support | Notes | Affected Files in ci/ |
|------------|----------------|-------|-----------------------|
| Python 3.8 | 14 October 2024 | | Dockerfile, Dockerfile.local, Dockerfile.userflow |
| Alpine Linux 3.15 | 1 November 2023 | | Dockerfile, Dockerfile.local |
| Postgres 11 | [9 November 2023](https://www.postgresql.org/support/versioning/) | | docker-compose.yml, docker-compose-local.yml, docker-compose-local-migrate.yml, docker-compose-test.yml |
| localstack | None given.  The YAML files specifies v0.12.3.  As of March 2022, v0.14.1 is available. | As of March 2022, localstack requires Python 3.6-3.9. | docker-compose-local.yml |
| bbyars/mountebank 2.4.0 | None given. | Newer versions are available. | docker-compose-local.yml |
| redis | | No version specified. | docker-compose-local.yml |

To update the images, change the `FROM` directive at the top of Dockerfiles and the `image` directive in YAML files.  Rebuild affected dependent containers, and run the [unit tests](#unit-testing) to verify the changes.  For example, if ci/Dockerfile begins with the line "FROM python:3.8-alpine3.15", you could change it to "FROM python:3.10-alpine3.15".  Visit Docker Hub to see what version tags are available for a given image.

---

## Deployment Workflow

### Update requirements.txt

The Docker image used in local development, ci/Dockerfile.local, builds with the Python packages given by requirements-app.txt, which specifies only the top level dependencies.  This ensures that the local image always builds with the most recent sub-dependencies, and developers only need to keep track of the top level dependencies.

The Docker image used in production, ci/Dockerfile, builds with the Python packages given by requirements.txt, which freezes all dependencies.  **Prior to any deployment to AWS, update requirements.txt as follows**:

1. If necessary, build the notification_api Docker image using the docker-compose command given in [Local Development](#local-development).
2. Run `docker run --rm -i notification_api pip freeze > requirements.txt`.
3. Open requirements.txt, and manually remove any warning messages at the start of the file.
4. Assuming all unit tests are passing, note any top level dependency updates.  Update requirements-app.txt to make their minimum version equal to the version actually installed according to requirements.txt.

## Creating a PR

When a ticket has been worked and is ready to be reviewed and merged in, we will create a new pull request (PR).

To open a PR:

- Make sure your branch is pushed up to the main repository

- The title of the PR should be formated to contain the ticket number of the issue being worked with a title

- The body should be filled out per the template that is provided

- Add in the correct tags that represent the PR

```markdown
Title: #443 Issue Title


# Description

Please include a summary of the change and which issue is fixed. Please also include relevant motivation and context. List any dependencies that are required for this change.

Fixes #443

## Type of change

Please delete options that are not relevant.

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] This change requires a documentation update

## How Has This Been Tested?

Please describe the tests that you ran to verify your changes. Provide instructions so we can reproduce. Please also list any relevant details for your test configuration

- [ ] Test A
- [ ] Test B

## Checklist

- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published in downstream modules
```

For tags, please make sure to add in additional tags to the PR based on the following categories:

```yaml
  categories:
    - title: Breaking Changes 🛠
      labels:
        - breaking-change
    - title: Exciting New Features 🎉
      labels:
        - enhancement
    - title: Bug Fixes 🐜
      labels:
        - bug
        - hotfix
    - title: Security Fixes 🔐
      labels:
        - cve
        - security
```

If the PR requires additional manual validation/testing then make sure to add in the `test` tag to the PR as well.

If the PR does not fit into these categories, then don't add a tag.

## Release Process

The API releases are managed by tags in the GitHub repo.

### Create a release for Perf

To create a new release, the user will create a new version tag in the git repository. This can be for the current `HEAD` or for a specific commit from a PR. The tag format will be `v(Major).(Minor).(Hotfix)` format. The Portal uses a similar method, so for version one of the Portal we created `v1.0.0` and with a single hotfix a new tag was created for `v1.0.1`.


Example commands for tagging:
```cli
git tag v2.0.0
git push origin v2.0.0
```

When a new tag is created with a `v` prefix and pushed to the repository, the tagging action will start. This action will checkout the tag, create testing notes based on PR's with the `test` tag applied to them, and then build and deploy to our performance (perf) environment.

### Create a release for Staging

After a tag has been deployed and the code is validated in perf, we create a `pre-release` for our staging environment.

- Login to GitHub and go to the notification-api repo. On the right side click on `Releases`

- Click on `Draft a new release`

- Select the tag to release from the `Choose a tag` dropdown

- Click on `Generate release notes` to generate the title and release notes for this release

- **Important**: Check the box `This is a pre-release`

- Click `Publish release` in order to push this pre-release

When a pre-release is created, the release action will trigger and this will pull the code from that tag, build a container, and deploy this to the staging environment. The pre-release will now be listed with the `pre-release` tag on the Releases page.

### Promote a release for Production

When a tag is ready to be moved to prodution, complete the following steps.

- Login to GitHub and go to the notification-api repo. On the right side click on `Releases`

- Select the pre-release tag to be updated and click on the penciel ✏️ icon in the upper right of the pre-release to edit

- Scroll to the bottom of the pre-release and find the checkbox for `This is a pre-release`

- Uncheck the box

- Click `Publish release` to push the release to production

When a release is generated it will trigger the release action which will checkout that tag, build and push the code to prodcution and deploy the new container.

---

##  To Run the Queues

VA Notify uses [Celery](https://docs.celeryq.dev/en/stable/) to run batches of processes.

- `scripts/run_celery.sh`
- `scripts/run_celery_beat.sh`

---

## AWS Lambda Functions

This repository contains lambda function code in the lambda_functions/ directory.  The AWS infrastructure resources are part of the [vanotify-infra](https://github.com/department-of-veterans-affairs/vanotify-infra) repository.  For information about creating lambda functions, refer to the [AWS documentation](https://docs.aws.amazon.com/lambda/index.html).

When creating a new lambda function, define an associated job in the Github workflow [Build Lambda Functions](.github/workflows/lambda-functions.yaml) using the naming convention `deploy-{functon name}-lambda`.

---

## Running Code Scans

The instructions below are for running locally.  The scans also are implemented as jobs in continuous integration pipeline.

[Bandit](https://pypi.org/project/bandit/) scans for common security issues in Python code.

```
make check-vulnerabiltiies
```

[Safety](https://pyup.io/safety/) checks python dependencies for known security vulnerabilities.

```
make check-dependencies
```

---

## Using our Endpoints

If you are trying to hit our endpoints while running the app locally, make sure you are using `http` and not `https.`
For all other environments, use `https` instead of `http`. If you get some sort of seemingly random error, double check
those first!

You will need to set several environment variables in order to get the endpoints to work properly. They are as 
follows:
- notification-api-url (either `127.0.0.1:6011` for local or our endpoints for everything else)
- notification-client-secret (the values for dev through prod should be in param store or 1Password)
- notification-admin-id: should be notify-admin for all environments
- api-key-id: not needed for local, should be in param store or 1Password for other environments

### Sending a notification

A lot of our endpoints in Postman have some scripting that saves ids to environment variables, so you might see some
of these variables populated after you make requests.

- Grab a service id by using the Get Services endpoint. This variable should be saved as service-id in env vars.
  VANotify is a good one to use.
- Find a template that you want to use on the service using the Get Templates for Service endpoint. Make sure it's
  same type as the notification you want to send (e.g., email, sms)
- Create or get a user id by making requests to Create User or Get Users. Make sure the user you get/create has
  permissions to send notifications. The id should be saved as user-id in env vars
- Create a service api key using the Create API Key endpoint. This variable should be saved as service-api-key in env
  vars
- Make a request with the various Send SMS/Email endpoints depending on your recipient. Once sent, the notification-id
  will be saved as an env var.
- To get updates on what's happening with the notification, you can make a request to the Notification Status endpoint
  and see what the notification_status currently is

---

## Testing Template Changes

Jinja templates are pulled in from the [notification-utils](https://github.com/department-of-veterans-affairs/notification-utils) repo.  Jinja templates used in this repo: `email_template.jinja2`. To test jinja changes locally without needing to push changes to notification-utils, follow this procedure:

1. Make markup changes to `email_template.jinja2` (notifications_utils/jinja_templates/email_template.jinja2)

2. (optional) Modify notifications_utils/version.py and add -SNAPSHOT to version number, e.g. `'version.number-SNAPSHOT'`.  This will allow to easily revert local copy of notifications-utils in sites-packages to official version from git.

3. From within the notification-api virtual environment reinstall the utils dependency into the api repo, run:

    ```commandline
    pip install file:///path/to/notification-utils
    ```
   
4. See the changes locally! 
    - Be sure the local server for notification-api is running to send an email. 
    - Refer to section [Installation for Local Development](###installation-for-local-development) for local setup or [Running in Docker](##running-in-Docker) for Docker command to local startup.

5. Repeat steps 1, 2 and 3 until satisfied.

6. When finished run:
    ```commandline
    pip install -r requirements.txt
    ```

---

## Using Mountebank Stubs

We have some stubs set up for making requests to MPI and VA Profile located in `scripts/mountebank/stubs`. In order to
hit these, start up the app locally with Docker and make sure the mountebank container is running properly.

To hit the MPI endpoints, make a POST request to send a notification with the following information instead of the
email/phone number in the payload:

```
"recipient_identifier": {
        "id_type": "PID",
        "id_value": <id value in stub url>
},
```

The ID value in the stub url is the number after `Patient/` and before the % sign (e.g., `400400` for
`/psim_webservice/fhir/Patient/400400%5EPI%5E200CORP%5EUSVBA$`).

For the VA Profile endpoints, make the same POST request to send a notification but use the following information
instead of an email/phone number in the payload:

```
"recipient_identifier": {
        "id_type": "VAPROFILEID",
        "id_value": <id value in stub url>
},
```

The ID value in the stub url is the number after `v1/` (e.g., `2003` for `/cuf/contact-information/v1/2003/emails$`).

---

For the VA Profile communication item endpoint, you will need to remove the port (`:443`) from the URL before you
make the request while running locally.

## Triggering Tasks

We have provided a script for executing a celery task located at `scripts/trigger_task.py`. In order to execute these,
you will first need to log into AWS using the CLI, and ensure that you have the developer role. You can then execute
the script for the command line given that you provide the task name, prefix and routing key for the queue, and any
required arguments to the task. For example, running the command

```
python scripts/trigger_task.py --task-name generate-daily-notification-status-report --queue-prefix dev-notification- --routing-key delivery-receipts --task-args 2022-01-28
```

Will run the `generate-daily-notification-status-report` task in the queue `dev-notification-delivery-receipts` with
a date string of `2022-01-28` passed to the task.

## Adding Environment Variables to Task Definition Files

When adding environment variables to any `<filename>-task-definition.json` file, make sure you add them to the corresponding
`celery`and `celery-beat` files as well. We want to try and keep these consistent with each other.

___

## Frequent problems

__Problem__: `assert 'test_notification_api' in db.engine.url.database, 'dont run tests against main db`

__Solution__: Do not specify a database in your `.env`

---

__Problem__: Messages are in the queue but not sending

__Solution__: Check that `celery` is running. 

---

__Problem__: Github Actions is failing when running the 'Perform twistlock scan' step of the 'build-and-push' job

__Solution__:

1. Navigate to [Twistlock UI](https://twistlock.devops.va.gov/#!/login)

2. Click Monitor -> Vulnerabilities -> Images -> CI

3. You should see your failing scan. Click on it to see what's going on. Usually the issue is due to a vulnerability
   that will be fixed soon in the alpine linux version that we're using; Twistlock will tell you the version with the
   fix if applicable.

4. If there is a fix, we can just ignore the Twistlock alert for a week because our alpine linux version will probably
   update to have the fix soon. Go to Defend -> Vulnerabilities -> CI to pull up the Vulnerability Rules.

5. Click on the existing Rule and scroll down to Exceptions. You can add your exception and set the expiration date to a
   week from now.

---

__Problem__: `./Modules/posixmodule.c:10432:5: warning: code will never be executed [-Wunreachable-code]
Py_FatalError("abort() called from Python code didn't abort!");`

This error may occur while attempting to install pyenv after updating to Big Sur.

__Solution__: Referenced from [this](https://github.com/pyenv/pyenv/issues/1739) Github issue.

Run the following command:

```
CFLAGS="-I$(brew --prefix openssl)/include -I$(brew --prefix bzip2)/include -I$(brew --prefix readline)/include -I$(xcrun --show-sdk-path)/usr/include" \
LDFLAGS="-L$(brew --prefix openssl)/lib -L$(brew --prefix readline)/lib -L$(brew --prefix zlib)/lib -L$(brew --prefix bzip2)/lib" \
pyenv install --patch 3.6.10 < <(curl -sSL https://github.com/python/cpython/commit/8ea6353.patch\?full_index\=1)
```
