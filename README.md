
# Djangotasks

Django-tasks is an asynchronous task management daemon, to execute long-running batch tasks (minutes, hours or even days) for Django applications.

## About

Django-tasks is for a different usage from most other tasks frameworks (Celery, Cue, etc.): this is not for numerous, quick, light, tasks, but for few, long, heavy, tasks. Typical usage is to batch process data for each model object, and give information about the processing to the user.

Also, no other software or library is needed. Django-tasks simply uses the Django database as a queue (and Tasks are a simple model); and each task is spawned as its own process.

## Version history

The current version (starting with 0.95) has a new API, much simplier than the API in previous versions (0.51, 0.52). If you used previous versions, you will need to modify your code -- but it should much simplier code.

The current API is not planned to change from now on; only some more real-world usage is needed (feedback and bugs welcome !).

Python 3 is supported starting with version 0.98.

## Main features

* Task starting, monitoring,
* Log gathering: at anytime, you can access the standard output created by your tasks,
* Start time, end time...
* Task dependency: only run a task of some other dependent task(s) have run (useful when multiple tasks require that one long processing has already happened),
* History (archive) of tasks already run on an object. This is helpful if there are errors or problem, to keep a log of what has run in the past,
* Basic admin view that lets you see what has been, or is, running,
* Events on task changes (start, end...),
* Cancel running tasks (kills the process).

This has been used in production for a hosted website in 2010; since then it has not been used much, but it has been updated recently, and all tests are passing.

It is tested on Linux and MacOS, and it should run on Windows (per [issue 16](https://code.google.com/p/django-tasks/issues/detail?id=16)); and on MySQL and SQLite (with some caveats for SQLite, see below).

The current version is tested on Django 1.10.5 with Python 2.7 and Python 3.5. Getting it to work with earlier versions of Django should not be difficult.

## Basic usage

On Django 1.10, follow these instructions to install and use:

1. Install djangotasks with pip: ```pip install git+git://github.com/farialima/django-tasks.git``` 

2. Add ```djangotasks``` Django application

	```INSTALLED_APPS += [ 'djangotasks' ]```

	Install the database for the application using:
    
	```python manage.py migrate djangotasks```

3. Write your long-running jobs' code

    Create a method _without parameter_ for a model, and add it the @task decorator:
    ```
    from djangotasks import task

    class MyModel(models.Model):
        @task
        def long_task(self):
            import time
            from djangotasks import current_task
            assert(current_task.is_running())
            time.sleep(10)
    ```

    Or for a function _without parameter_:

    ```
    from djangotasks import task

    @task
    def long_function():
         import time
         from djangotasks import current_task
         assert(current_task.is_running()) # by definition
         time.sleep(10)
    ```
    Note that methods or functions with parameters are not supported; and passing parameter as global variable will not work, as the task will run in a different thread and process.

    Run your tasks from [Django View](https://docs.djangoproject.com/en/dev/topics/http/views/) or [Django Admin Action](https://docs.djangoproject.com/en/dev/ref/contrib/admin/actions/) using the following code. 
    In ```views.py``` (_not tested_):
    ```
    import djangotasks

    def test_view(request):
        task = my_model_object.long_task()
        task = task.run()
        id = task.id
        return HttpResponse(task.id)
    ```
    Or in ```admin.py```:
    ```
    from .models import MyModel
    import djangotasks

    def run_my_model_longtask(modeladmin, request, queryset):
        for my_model_object in queryset:
            task = my_model_object.long_task()
            task.run()

    run_my_model_longtask.short_description = "My first long running task admin action"


    class MyModelAdmin(admin.ModelAdmin):
        actions = [ run_my_model_longtask,]

    admin.site.register(MyModel, MyModelAdmin)
    ```

    Register your app in settings.py

    ```INSTALLED_APPS += [ 'my_app' ]```

    Install the database for the application using:
    
    ```python manage.py makemigrations && python manage.py migrate```
    

4. Run the task daemon with ```python manage.py taskd start```

	It can run either as a thread in your process (provided you only run one server process) or as a separate daemon. To run it in-process (as a thread), just set ```DJANGOTASK_DAEMON_THREAD = True``` in your ```settings.py```. Do not run as a thread in production, only use as an external daemon.

	Now you can view the status of your task in the 'Djangotasks' Admin module.

	You can of course use the Task model in your own models and views, to provide specific user interface for your own tasks, or poll the status of the task.

	In your code, you can also add things like:
   ``` 
   	   task = my_model_object.long_method()
       print task.log
       if task.is_running();
          task.cancel()
      
       tasks = task.archives()
       # etc...
   ```

5. Advanced usage: dependent tasks

You can define dependencies in your tasks. It will ensure that dependent tasks will run (finish and succeed) before the depending tasks -- but will not re-run if they have already successfully run. 

To define a dependency, simply make sure that the dependent task has the `@task` decorator, and then pass it as a parameter to the `@task` decorator of the depending task. For example:

    ``` 
    class MyModel(models.Model):
        @task
        def run_first(self):
           print "I run first"

        @task(run_first):
        def run_then(self):
           print "I run second, if first has succeeded"

     ```


### Development and testing

To run the tests, create a project and add the ```djangotasks``` app to it.

The tests cannot run on SQLite, as they access the database from multiple threads: they can only run on MySQL (or probably PostgreSQL, but not tested).

You must specify a test database name in your settings:
```
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'your-db-name',
        'USER': 'your-db-user',
        'PASSWORD': 'your-db-password',
        'HOST': 'localhost',   # Or an IP Address that your DB is hosted on
        'PORT': '3306',
        'TEST': {
            'NAME': 'djangotasks-test',
            'SERIALIZE': False
        },
    }
}
```
Then run the tests normally using ```manage.py test```.


