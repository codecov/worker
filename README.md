# worker
[![Circle CI](https://circleci.com/gh/codecov/worker.png?style=badge&circle-token=885f572a99c95211064d4b97deb1de96e84e1352)](https://circleci.com/gh/codecov/worker) [![worker](https://codecov.io/github/codecov/worker/coverage.svg?branch=master&token=P4Uxn9nj57)](https://codecov.io/github/codecov/worker)
Code for Background Workers of Codecov. This is built on top of the `celery` async framework

## Quickstart

After cloning this, run

```
pip install -r requirements.txt
```
(Make sure you have access to the repos listed there. A couple of them are private and are under the codecov organization)

Then, try to run tests to see if the code is working. First get some database running. Anything is fine. I like to spin a `postgres` docker. Then do

```
make test
```

To build this into a docker image:

```
make build
```

To run this as part of the whole infrasctructure, you will be better served by getting the main database and running `docker-compose up` from there

## Code Structure

Before getting into changing the code, try to use the following structure (feel free to suggest changes.Some bits of it are based on our experience)

- `helpers` - Those are the "low" level pieces of code, that don't depend on database models or any other heavy business logic. Those shouldn't depend on anything else on the codebase, preferrably
- `database` - Those contain database models. They can use logic from `helpers` and other models, but nothing else. Try to avoid any heavy logic in this code.
- `services` - Those are heavier pieces of logic, that don't talk to the external world. They can use `helpers` and `database` logic, and among themselves. But make sure that if a service _bravo_ depends on service _alpha_, then _alpha_ should not depend on any part of _bravo_
- `tasks` - Those are the parts of the code that talk to the external world: it has the tasks that are triggered by external containers. They can depend on `helpers`, `models` and `services`, but NEVER depend on another task (except to schedule them). If some code is common to two tasks, try to put it in a `service` or somewhere else.

You will also notice some usage of the package https://github.com/codecov/report for various things. The name is weird, but this is basically a package that now holds all code that is common to this service and https://github.com/codecov/codecov-api
