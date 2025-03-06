# Tasks

The actual tasks that power the worker live on this folder.

The task system is powered by [celery](https://docs.celeryproject.org/en/latest/index.html).

If you don't understand tasks well, you can see them as the Django (or your favorite web framework) views from this system. They are the entrypoint to talking to the workers.

## Existing tasks

Please take a look at the code in this directory (the `tasks` directory)
to get all the tasks defined.

## Rules about tasks

As described in the repo README, there should be a couple of cares when using tasks:

1. Tasks, just like Django views, are an entrypoint to the external world. A lot of the task is about doing wiring, ie, properly parsing and organizing data structures so the actual logic doesn't have to.

2. There is only so much logic a task should have. The heavier the logic gets, the more sensible it is to move them to services.
    - A good example is how `NotifyTask` and `NotificationService` interact. Even though `NotifyTask` is the only place that uses `NotificationService` nowadays, it was sensible to create `NotificationService` to deal with the actual intricacies of starting the right notifications, collecting results and handling errors. What the task does is collect the proper config yamls, the proper Report objects, pass them over to the service and then collect the results of the notifications, while handling top level things like retries and some higher-level rules.
    - There are exceptions to this rule. It is ok to hold heavier logic in a task if you feel the logic is too specific to it and wouldn't be easily used anywhere else without a lot of interfacing compromises. But even in those cases, move the logic away from the main function and put them on a different method

3. Tasks, just like views, are meant to be on their own. We should not import logic pieces from one task to another (nor to anywhere else). If something is useful to two different tasks, consider putting the shared logic in a service (see point above) and then importing that service on both tasks. Just make sure the service interface (method signatures and return type, for example) are not too specific to the tasks you are calling.

4. It is ok for tasks to schedule other tasks (which is different than directly calling code from them), but it is not ok for a task to wait for other task to finish. This is the textbook example of causes of a deadlock. If you really need to coordinate different tasks, consider using celery's built-in tools, like chaining/grouping/chording tasks.

5. Tasks should not receive complex types as parameters at their main function. The only acceptable basic types for a task to receive as parameter are int, float, str. Lists and dicts are acceptable as long as they only contain other acceptable types. Avoid temptation to use Enums, for example, even if they look easy enough to deal with (been there, broke that). After the main function, feel free to pass whatever you want to whoever you want, since you are already inside your own python code anyway.
    - The reason for that is about how those tasks are serialized and deserialized when sent to the worker. Task arguments are stored to redis ( or another non-python queue system) when it's scheduled. So its data (read, arguments) has to be serialized to a no-python-specific format in order to be saved there and deserialized when it gets back to python.
    - The most two common serializers provided out of the box by celery are `json` (current default) and `pickle` (previous default)
    - `pickle` is a system that python users for serializer/deserializing python objects. It's a very sensitive to changs in the the code. Such that in some "simple" changes can unexpectedely make the pickler crash with old versions of a pickled object. Add this to point number 8 below, and there is a risk of the pickler crashing on each deploy. Also, pickle stopped being the default for a reason (security purposes and harder to read when the data on redis)
    `json` is only meant for json-serializable objects (which are only the above-allowed objects). Hooking it with your own serializer/deserializer for getting custom objects opens its own can of worms. It's usually cleaner and easier to pass a "dried-up" version of the object (like its id or a dict containing all its relevant info) and "hydrate" the object yourself inside the function.

6. Task return types usually don't matter much, but be aware that our system is not meant to have the task returned values used anywhere else. A normal practice is to return a small dict with some decent information about the task general result. This eases testing and the results are also logged to some extent on datadog.
    - They aren't used anywhere because a) they aren't saved anywhere, and b) some of them they take so long, that there is not a sensible way to make customers wait for them.
    -  If there is ever an interest on getting actual returned values from tasks, we might need to put them on their own queue with their own workers, so they don't suffer from waiting for other long-running tasks to finish.

7. Testing tasks should be done at two levels: unit and integration. The reasons are the same reasons one would unit-test and integration-test any system. It just happens that tasks are the best candidate inside the worker to see something from start to finish.

8. This worker system, by its very own nature, is asynchronous. So you should never be reliant on good timing for deploys and or coordinating changes. Deploys don't happen on all machines at once (not within the worker system, let alone when coordinating different systems deploys). So the system should be prepared during a deploy of "new_version" code, that
    - "new_version" workers will send tasks that will be processed by "old_version" workers
    - "old_version" workers will send tasks that will be processed by "new_version" workers
    - A deploy on web might be happening at the same time, and both new_web and old_web workers will send tasks to both old_version worker and new_version workers.

9. Tasks are the only things in the worker system that are allowed to do actual database `COMMIT;`s. The base class mixin will already take care of commit the changes for you at the end of the task either way, but feel free to commit earlier whenever it is needed
    - This is done so the services can all build on top of each other with the safety that they will not unexpectedly do a db commit before the caller is ready to commit that data.
    - This also frees `services` functions to do nested db transactions without any function it calls accidentally commiting the nested transaction

## Adding new tasks

When adding a new task, you will already have a ton you need to do. But be sure to:

1. Import that task on the [init file](./__init__.py)
2. Add a name to it. Or don't. But add whatever its name is to the [celery configuration](../celery_config.py)
3. Don't start scheduling things to it right away (see point above about the system being asychronous)
4. Make sure celery displays it when spinning up the system on your local machine

You should be able to copy-paste any of the tasks when creating your own, but the important entrypoint of the task is the `run_impl` function.

It needs to have

* `self` as the first parameter (normal python class stuff)
* `db_session` as the second one (for getting access to the db, but even if you don't need db, you should have this argument)
* The arguments you want to have this function receive as input. Notice they will always be expected to be called as keyword parameters (ie, passing the name of the argument right at the function call instead of just putting them in the right order), so it is recommended to add `*` before them.
* Type the expected parameters as well.
* `**kwargs` - This is a safety measure to ensure that this function won't go crazy whenever you want to add more parameters to it.
* In the end, your function signature should look a bit like this:

```
    def run_impl(
        self,
        db_session: Session,
        *,
        repoid: int,
        commitid: str,
        current_yaml=None,
        **kwargs,
    ):
```


