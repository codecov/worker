# worker

[![Circle CI](https://circleci.com/gh/codecov/worker.png?style=badge&circle-token=885f572a99c95211064d4b97deb1de96e84e1352)](https://circleci.com/gh/codecov/worker) [![worker](https://codecov.io/github/codecov/worker/coverage.svg?branch=master&token=BWTOrjBaE5)](https://codecov.io/github/codecov/worker)


Code for Background Workers of Codecov. This is built on top of the `celery` async framework

## Quickstart

### Setting Virtual Env

Before starting, we suggest using a virtual environment for this project. It eases testing in general at least.

If you already know how to do it (and how you like it), just do what you already do. If you dont know how to do it, we suggest the following steps:

- `python3 -m venv workerenv`
- `cd workerenv`
- `source bin/activate`

Then you should clone this project when inside `workerenv` folder.

### Installing dependencies

Make sure to:
- Install rust. See https://www.rust-lang.org/tools/install
- Have access to any private codecov repos listed in the requirements.txt file. See [here](https://codecovio.atlassian.net/wiki/spaces/ENG/pages/1270743045/Setup) for help on getting that set up.

To install the dependencies, run

```
pip install -r requirements.txt
```

### Running Tests

Then, try to run tests to see if the code is working. First get some postgres database running. Anything is fine. I like to spin a `postgres` docker (`docker run -d -p 5432:5432 postgres:9.6.16`). Then do

```
make test
```

### Getting into docker

To build this into a docker image:

```
make build.base
make build
```

To run this as part of the whole infrasctructure, you will be better served by getting the main codebase and running `docker-compose up` from there

### Getting into enterprise mode

To generate an enterprise build, do

```
make build.enterprise
```

## Versioning

The source of truth on which version we use is in the file `VERSION`. Every script that tags things with versions will consult that file to see what version it is.

That file is manually updated. We use semantic versioning.

If you are unsure whether you need to change that version at a given moment, the answer is that you probaby don't then. We have multiple deploys on the same version, and only change it when we want to cut a version to enterprise.

## Upgrading Dependencies

This repository uses `pip-tools` to manage dependencies, so make sure you've installed it with `pip install pip-tools`. To add or update dependencies, change `requirements.in`,  Then run

```
pip-compile requirements.in
```

Do not change `requirements.txt` directly

## Deploying

To deploy, all you have to do is create a release (preferred option) or push a tag with the pattern production-date-number. More specifically, it needs to follow the regex:

```
^production-[0-9]{4}-[0-9]{2}-[0-9]{4}
```

Which means, for example:

- `production-2020-11-0001` - First deploy of 2020-11
- `production-2020-12-0015` - Fifteenth deploy of 2020-12

Notice that, while the dates are really useful for understanding when code was deployed, it doesn't affect whether or not your release will go to production. If your regex matches the pattern, regardless of what date is tagged, that version will go to production.

To create releases on Github, you can go to https://github.com/codecov/worker/releases or use Github CLI. to push tags you can follow instructions on https://git-scm.com/book/en/v2/Git-Basics-Tagging

### After deploying

If you are deploying or helping with a deploy, make sure to:

1. Watch logs (on datadog and sentry)
2. Monitor error rates and timing graphs on the dashboards we have set up

As the deployer, it is your responsability to make sure the system is working as expected post-deploy. If not, you might need to do a rollback.

## Code Structure

Before getting into changing the code, try to use the following structure (feel free to suggest changes.Some bits of it are based on our experience)

- `helpers` - Those are the "low" level pieces of code, that don't depend on database models or any other heavy business logic. Those shouldn't depend on anything else on the codebase, preferrably
- `database` - Those contain database models. They can use logic from `helpers` and other models, but nothing else. Try to avoid any heavy logic in this code.
- `services` - Those are heavier pieces of logic, that don't talk to the external world. They can use `helpers` and `database` logic, and among themselves. But make sure that if a service _bravo_ depends on service _alpha_, then _alpha_ should not depend on any part of _bravo_
- `tasks` - Those are the parts of the code that talk to the external world: it has the tasks that are triggered by external containers. They can depend on `helpers`, `models` and `services`, but NEVER depend on another task (except to schedule them). If some code is common to two tasks, try to put it in a `service` or somewhere else.

You will also notice some usage of the package https://github.com/codecov/shared for various things. The logic that is there is used by both here and `codecov/api` codebase. So feel free to make changes there, but dont do anything that will break compatibility too hard.
