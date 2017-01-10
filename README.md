# Djangotasks

Django-tasks is an asynchronous task management daemon, to execute long-running batch tasks (minutes, hours or even days) for Django applications.

The following repo is the clone of original repo at [Google Code](http://code.google.com/p/django-tasks/).

Current version is formed from revision r51 of original SVN repo. 


## About

Django-tasks is for a different usage from most other tasks frameworks (Celery, Cue, etc.): this is not for numerous, quick, light, tasks, but for few, long, heavy, tasks. Typical usage is to batch process data for each model object, and give information about the processing to the user.

Also, no other software or library is needed. Django-tasks simply uses the Django database as a queue (and Tasks are a simple model); and each task is spawned as its own process.

## Main features

* Task starting, monitoring
* Log gathering: at anytime, you can access the standard output created by your tasks,
* Start time, end time... of course
* Task dependency: only run a task of some other dependent task(s) have run (useful when multiple tasks require that one long processing has already happened),
* History (archive) of tasks already run on an object. This is helpful if there are errors or problem, to keep a log of what has run in the past,
* Basic admin view that lets you see what has been, or is, running,
* Events on task changes (start, end...)
* Cancel running tasks (kills the process).

This has been used in production for a hosted website in 2010; since then it has not been used much, but it has been updated recently, and all tests are passing.

It is tested on Linux and MacOS, and it should run on Windows (per [issue 16](https://code.google.com/p/django-tasks/issues/detail?id=16)); and on PostgreSQL and SQLite (with some caveats for SQLite, see below).

The current version is tested on Django 1.10 with Python 2.7. Making it work with earlier versions of Django should not be difficult. It is not (yet) working with Python 3, but should soon.

## Basic usage

On Django 1.10, follow the instructions to use Django tasks. 

1. Install djangotasks with pip: ```pip install git+git://github.com/farialima/django-tasks.git``` 

2. Add ```djangotasks``` Django application

```INSTALLED_APPS += [ 'djangotasks' ]```

Install the database for the application using:
```python manage.py migrate djangotasks```

3. Write your long-running jobs' code

    Create method for any of your models:
    ```
    class MyModel(models.Model):
        def long_task(self):
            import time
            time.sleep(10)
    ```

    In your ```models.py``` also, register the task:
    ```
    import djangotasks
    djangotasks.register_task(MyModel.long_task, "My first long running task")
    ```

    Run your tasks from [Django View](https://docs.djangoproject.com/en/dev/topics/http/views/) or [Django Admin Action](https://docs.djangoproject.com/en/dev/ref/contrib/admin/actions/) using the following code. 
    In ```views.py``` (_not tested_):
    ```
    import djangotasks

    def test_view(request):
        task = djangotasks.task_for_object(my_model_object.long_task)
        djangotasks.run_task(task)
        return HttpResponse(task.id)
    ```
    Or in ```admin.py```:
    ```
    from .models import MyModel
    import djangotasks

    def run_my_model_longtask(modeladmin, request, queryset):
        for my_model_object in queryset:
            task = djangotasks.task_for_object(my_model_object.long_task)
            djangotasks.run_task(task)

    run_my_model_longtask.short_description = "My first long running task admin action"


    class MyModelAdmin(admin.ModelAdmin):
        actions = [run_my_model_longtask,]

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


### Development and testing

To run the tests, create a project and add the ```djangotasks``` app to it.

The tests cannot run on SQLite, as they access the database from multiple threads: they can only run on MySQL (or possibly PostgreSQL, but not tested).

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


