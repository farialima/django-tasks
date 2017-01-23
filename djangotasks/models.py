#
# Copyright (c) 2010-2017 by nexB, Inc. http://www.nexb.com/ - All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
# 
#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.
#    
#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
# 
#     3. Neither the names of Django, nexB, Django-tasks nor the names of the contributors may be used
#        to endorse or promote products derived from this software without
#        specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import time
import sys
import time
import subprocess
import logging
from collections import defaultdict
from os.path import join, exists, dirname, abspath


from django.apps import apps
from django.conf import settings
from django.db import transaction, connection, models
from django.utils import timezone
from django.utils.encoding import smart_unicode

from djangotasks import signals

LOG = logging.getLogger("djangotasks")

def _get_model_name(model_class):
    return smart_unicode(model_class._meta)

def _get_model_class(model_name):
    model = apps.get_model(*model_name.split("."))
    if model == None:
        raise Exception("%s is not a registered model, cannot use this task" % model_name)
    return model


class TaskManager(models.Manager):
    '''The TaskManager class is not for public use. 

    The package-level API should be sufficient to use django-tasks.
    '''


    # When executing a task, the current task being executed. 
    # Since only one task is executed per process, this can be a static.
    current_task = None

    def task_for_object(self, object, method, dependents=None, status_in=None):
        import inspect
        if len(inspect.getargspec(method)[0]) != 1:
            raise Exception("Cannot use tasks on a method that has parameters")

        dependent_names = [ dependent_method.wrapped_method_or_function.__name__ for dependent_method in dependents ] if dependents else None
        return self._task_for_object(object.__class__, object.pk,
                                     method.__name__, dependent_names, status_in)

    def _task_for_object(self, object_class, object_id, method_name, dependents, status_in=None):
        if not object_id:
            raise Exception("The object must first be saved in the database")
        model_name = _get_model_name(object_class)
        if status_in == None:
            status_in = dict(STATUS_TABLE).keys()
            
        from django.core.exceptions import MultipleObjectsReturned
        try:
            task, created = self.get_or_create(model=model_name, 
                                               method=method_name,
                                               object_id=str(object_id),
                                               status__in=status_in,
                                               archived=False, 
                                               dependents=(','.join(dependents) if dependents else None))
        except MultipleObjectsReturned, e:
            LOG.exception("Integrity error: multiple non-archived tasks, should not occur. Attempting recovery by archiving all tasks for this object and method, and recreating them")
            objects = self.filter(model=model_name, 
                                  method=method_name,
                                  object_id=str(object_id),
                                  status__in=status_in,
                                  archived=False).update(archived=True)
            task, created = self.get_or_create(model=model_name, 
                                               method=method_name,
                                               object_id=str(object_id),
                                               status__in=status_in,
                                               archived=False)

        LOG.debug("Created task %d on model=%s, method=%s, object_id=%s", task.id, model_name, method_name, object_id)
        return self.get(pk=task.pk)

    def task_for_function(self, function, dependents=None):
        function_name = _to_function_name(function)
        function_task = FunctionTask.objects.get_or_create(function_name=function_name)
        dependent_names = [ _to_function_name(dependent_function.wrapped_method_or_function) 
                            for dependent_function in dependents ] if dependents else None
        return self._task_for_object(FunctionTask, function_name, "run_function_task", dependent_names)

    def run_task(self, pk):
        task = self.get(pk=pk)
        self._run_dependent_tasks(task)
        if task.status in ["scheduled", "running"]:
            return task
        if task.status in ["requested_cancel"]:        
            raise Exception("Task currently being cancelled, cannot run again")
        if task.status in ["cancelled", "successful", "unsuccessful"]:
            task = self._create_task(task.model, 
                                     task.method, 
                                     task.object_id,
                                     task.dependents)
            
        self.filter(pk=task.pk).update(status="scheduled")
        return self.get(pk=task.pk)

    def _run_dependent_tasks(self, task):
        for dependent_task in task.get_dependent_tasks():
            self._run_dependent_tasks(dependent_task)

            if dependent_task.status in ['scheduled', 'successful', 'running']:
                continue
            
            if dependent_task.status == 'requested_cancel':
                raise Exception("Dependent task being cancelled, please try again")

            if dependent_task.status in ['cancelled', 'unsuccessful']:
                # re-run it
                dependent_task = self._create_task(dependent_task.model, 
                                                  dependent_task.method, 
                                                  dependent_task.object_id,
                                                  dependent_task.dependents)

            dependent_task.status = "scheduled"
            dependent_task.save()

    def cancel_task(self, pk):
        task = self.get(pk=pk)
        if task.status not in ["scheduled", "running"]:
            raise Exception("Cannot cancel task that has not been scheduled or is not running")

        # If the task is still scheduled, mark it requested for cancellation also:
        # if it is currently starting, that's OK, it'll stay marked as "requested_cancel" in mark_start
        self._set_status(pk, "requested_cancel", ["scheduled", "running"])
        return self.get(pk=task.pk)


    # The methods below are for internal use on the server. Don't use them directly.
    def _create_task(self, model, method, object_id, dependents):
        return Task.objects._task_for_object(_get_model_class(model), object_id, method, dependents,
                                             ["defined", "scheduled", "running", "requested_cancel"])

    def append_log(self, pk, log):
        if log:
            # not possible to make it completely atomic in Django, it seems
            rowcount = self.filter(pk=pk).update(log=(self.get(pk=pk).log + log))
            if rowcount == 0:
                raise Exception(("Failed to save log for task %d, task does not exist; log was:\n" % pk) + log)

    def mark_start(self, pk, pid):
        # Set the start information in all cases: That way, if it has been set
        # to "requested_cancel" already, it will be cancelled at the next loop of the scheduler
        rowcount = self.filter(pk=pk).update(pid=pid, start_date=timezone.now())
        if rowcount == 0:
            raise Exception("Failed to mark task with ID %d as started, task does not exist" % pk)

    def _set_status(self, pk, new_status, existing_status):
        if isinstance(existing_status, str):
            existing_status = [ existing_status ]
            
        if existing_status:
            rowcount = self.filter(pk=pk).filter(status__in=existing_status).update(status=new_status)
        else:
            rowcount = self.filter(pk=pk).update(status=new_status)
        if rowcount == 0:
            LOG.warning('Failed to change status from %s to "%s" for task %s',
                        "or".join('"' + status + '"' for status in existing_status) if existing_status else '(any)',
                        new_status, pk)

        return rowcount != 0

    def mark_finished(self, pk, new_status, existing_status):
        rowcount = self.filter(pk=pk).filter(status=existing_status).update(status=new_status, end_date=timezone.now())
        if rowcount == 0:
            LOG.warning('Failed to mark tasked as finished, from status "%s" to "%s" for task %s. May have been finished in a different thread already.',
                        existing_status, new_status, pk)
        else:
            LOG.info('Task %s finished with status "%s"', pk, new_status)
            # Sending a task completion Signal including the task and the object
            task = self.get(pk=pk)
            try:
                object = _get_model_class(task.model).objects.get(pk=task.object_id)
            except Exception, e:
                print "PK =", task.object_id
                raise # Exception("PK = " + str(task.object_id))
            signals.task_completed.send(sender=self, task=task, object=object)
    
    # This is for use in the scheduler only. Don't use it directly.
    def exec_task(self, task_id):
        if self.current_task:
            raise Exception("Task already running running in process")
        try:
            self.current_task = self.get(pk=task_id)

            the_class = _get_model_class(self.current_task.model)
            the_object = the_class.objects.get(pk=self.current_task.object_id)

            # bind the method to the object...
            the_method =  getattr(the_object, self.current_task.method).wrapped_method_or_function.__get__(the_object, the_object.__class__)

            the_method()
        finally:
            import sys
            sys.stdout.flush()
            sys.stderr.flush()
    
    # This is for use in the scheduler only. Don't use it directly
    def scheduler(self):
        # Run once to ensure exiting if something is wrong
        try:
            self._do_schedule()
        except:
            LOG.fatal("Failed to start scheduler due to exception", exc_info=1)
            return

        LOG.info("Scheduler started")
        while True:
            # Loop time must be enough to let the threads that may have be started call mark_start
            time.sleep(5)
            try:
                self._do_schedule()
            except:
                LOG.exception("Scheduler exception")

    def _do_schedule(self):
        # First cancel any task that needs to be cancelled...
        tasks = self.filter(status="requested_cancel",
                            archived=False)
        for task in tasks:
            LOG.info("Cancelling task %d...", task.pk)
            task._do_cancel()
            LOG.info("...Task %d cancelled.", task.pk)

        # ... Then start any new task
        tasks = self.filter(status="scheduled",
                            archived=False)
        for task in tasks:
            # only run if all the dependent tasks have been successful
            if any(dependent_task.status == "unsuccessful"
                   for dependent_task in task.get_dependent_tasks()):
                task.status = "unsuccessful"
                task.save()
                continue

            if all(dependent_task.status == "successful"
                   for dependent_task in task.get_dependent_tasks()):
                LOG.info("Starting task %s...", task.pk)
                task.do_run()
                LOG.info("...Task %s started.", task.pk)
                # only start one task at a time
                break

STATUS_TABLE = [('defined', 'ready to run'),
                ('scheduled', 'scheduled'),
                ('running', 'in progress',),
                ('requested_cancel', 'cancellation requested'),
                ('cancelled', 'cancelled'),
                ('successful', 'finished successfully'),
                ('unsuccessful', 'failed'),
                ]

          
class Task(models.Model):

    model = models.CharField(max_length=200)
    method = models.CharField(max_length=200)
    
    object_id = models.CharField(max_length=200)
    pid = models.IntegerField(null=True, blank=True)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=200,
                              default="defined",
                              choices=STATUS_TABLE,
                              )

    log = models.TextField(default='', null=True, blank=True)

    archived = models.BooleanField(default=False) # for history

    # comma-separated list of dependent methods
    dependents = models.TextField(default=None, null=True)

    def __unicode__(self):
        return u'%s - %s.%s.%s' % (self.id, self.model.split('.')[-1], self.object_id, self.method)

    def status_string(self):
        return dict(STATUS_TABLE)[self.status]

    def status_for_display(self):
        return '<span class="%s">%s</span>' % (self.status, self.status_string())

    status_for_display.allow_tags = True
    status_for_display.admin_order_field = 'status'
    status_for_display.short_description = 'Status'

    def complete_log(self, directly_dependent_only=False):
        return '\n'.join([dependent_task.formatted_log() 
                          for dependent_task in self._unique_dependent_tasks(directly_dependent_only)])

    def get_dependent_tasks(self):
        if not self.dependents:
            return []
        
        the_class = _get_model_class(self.model)
        if the_class == FunctionTask:
            # dependents are function names
            return [ _to_function(function_name)()
                     for function_name in self.dependents.split(',') ]
        else:
            the_object = the_class.objects.get(pk=self.object_id)
            return [ getattr(the_object, method)()
                     for method in self.dependents.split(',') ]
    
    def can_run(self):
        return self.status not in ["scheduled", "running", "requested_cancel", ] #"successful"

    def is_runing(self):
        return self.status == "running"

    def run(self):
        return Task.objects.run_task(self.pk)

    def cancel(self):
        return Task.objects.cancel_task(self.pk)

    def archives(self):
        '''returns all previous runs of this task for this object'''
        return Task.objects.filter(model=self.model, 
                                   method=self.method,
                                   object_id=self.object_id,
                                   archived=True)

    def formatted_log(self):
        from django.utils.dateformat import format
        FORMAT = "N j, Y \\a\\t P T"
        description = self.model + '.' + self.method + '(pk = ' + str(self.object_id) + ') '
        if self.status in ['cancelled', 'successful', 'unsuccessful']:
            return (description + 'started' + ((' on ' + format(self.start_date, FORMAT)) if self.start_date else '') +
                    (("\n" + self.log) if self.log else "") + "\n" +
                    description + self.status_string() + ((' on ' + format(self.end_date, FORMAT)) if self.end_date else '') +
                    (' (%s)' % self.duration if self.duration else ''))
        elif self.status in ['running', 'requested_cancel']:
            return (description + 'started' + ((' on ' + format(self.start_date, FORMAT)) if self.start_date else '') +
                    (("\n" + self.log) if self.log else "") + "\n" +
                    description + self.status_string())
        else:
            return description + self.status_string()
                    
    # Only for use by the manager: do not call directly, except in tests
    def do_run(self):
        if self.status != "scheduled":
            raise Exception("Task not scheduled, cannot run again")

        def exec_thread():
            returncode = -1
            try:
                # Do not start if it's not marked as scheduled
                # This ensures that we can have multiple schedulers
                if not Task.objects._set_status(self.pk, "running", "scheduled"):
                    return
                # execute the managemen utility, with the same python path as the current process
                env = dict(os.environ)
                env['PYTHONPATH'] = os.pathsep.join(sys.path)
                proc = subprocess.Popen([sys.executable, 
                                         '-c',
                                         'import sys; from django.core.management import execute_from_command_line; execute_from_command_line(sys.argv)',
                                         "runtask", str(self.pk),
                                         ],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        close_fds=(os.name != 'nt'), 
                                        env=env)
                Task.objects.mark_start(self.pk, proc.pid)
                buf = ''
                t = time.time()
                while proc.poll() is None:
                    line = proc.stdout.readline()
                    buf += line
                    if (time.time() - t > 1): # Save the log once every second max
                        Task.objects.append_log(self.pk, buf)
                        buf = ''
                        t = time.time()

                Task.objects.append_log(self.pk, buf) 
               
                # Need to continue reading for a while: sometimes we miss some output
                buf = ''
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    buf += line
                Task.objects.append_log(self.pk, buf)

                returncode = proc.returncode

            except Exception, e:
                LOG.exception("Exception in calling thread for task %s", self.pk)
                import traceback
                stack = traceback.format_exc()
                try:
                    Task.objects.append_log(self.pk, "Exception in calling thread: " + str(e) + "\n" + stack)
                except Exception, ee:
                    LOG.exception("Second exception while trying to save the first exception to the log for task %s!", self.pk)

            Task.objects.mark_finished(self.pk,
                                       "successful" if returncode == 0 else "unsuccessful",
                                       "running")

        import thread
        thread.start_new_thread(exec_thread, ())

    def _do_cancel(self):
        if self.status != "requested_cancel":
            raise Exception("Cannot cancel task if not requested")

        try:
            if not self.pid:
                # This can happen if the task was only scheduled when it was cancelled.
                # There could be risk that the task starts *while* we are cancelling it, 
                # and we will mark it as cancelled, but in fact the process will not have been killed/
                # However, it won't happen because (in the scheduler loop) we *wait* after starting tasks, 
                # and before cancelling them. So no need it'll happen synchronously.
                return
                
            import signal
            os.kill(self.pid, signal.SIGTERM)
        except OSError, e:
            # could happen if the process *just finished*. Fail cleanly
            raise Exception('Failed to cancel task model=%s, method=%s, object=%s: %s' % (self.model, self.method, self.object_id, str(e)))
        finally:
            Task.objects.mark_finished(self.pk, "cancelled", "requested_cancel")

    def _unique_dependent_tasks(self, directly_dependent_only=False):
        unique_dependent_tasks = []
        for dependent_task in self.get_dependent_tasks():
            if directly_dependent_only:
                if dependent_task not in unique_dependent_tasks:
                    unique_dependent_tasks.append(dependent_task)
            else:
                for unique_dependent_task in dependent_task._unique_dependent_tasks():
                    if unique_dependent_task not in unique_dependent_tasks:
                        unique_dependent_tasks.append(unique_dependent_task)
        if self not in unique_dependent_tasks:
            unique_dependent_tasks.append(self)
        return unique_dependent_tasks

    def save(self, *args, **kwargs):
        if not self.pk:
            # time to archive the old ones
            Task.objects.filter(model=self.model, 
                                method=self.method,
                                object_id=self.object_id,
                                archived=False).update(archived=True)

        super(Task, self).save(*args, **kwargs)

    def _compute_duration(self):
        if self.start_date and self.end_date:
            delta = self.end_date - self.start_date
            min, sec = divmod((delta.days * 86400) + delta.seconds, 60)
            hour, min = divmod(min, 60)
            str = ((hour, 'hour'), (min, 'minute'), (sec, 'second'))
            return ', '.join(['%d %s%s' % (x[0], x[1],'s' if x[0] > 1 else '')
                              for x in str if (x[0] > 0)])

    duration = property(_compute_duration)
            
    objects = TaskManager()

def _to_function_name(function):
    import inspect
    if not inspect.isfunction(function):
        raise Exception(repr(function) + " is not a function")
    return function.__module__ + '.' + function.__name__


def _to_function(function_name):
    module_segments = function_name.split('.')
    module = __import__('.'.join(module_segments[:-1]))
    for segment in module_segments[1:]:
        module = getattr(module, segment)
    return module


class FunctionTask(models.Model):
    function_name = models.CharField(max_length=255,
                                     primary_key=True)
    from djangotasks import task
    @task
    def run_function_task(self):
        function = _to_function(self.function_name).wrapped_method_or_function
        return function()


# TODO: for simplicity, we always include the test model... this should not be the case, of course
from djangotasks.tests import TestModel

if 'DJANGOTASK_DAEMON_THREAD' in dir(settings) and settings.DJANGOTASK_DAEMON_THREAD:
    import logging
    logging.getLogger().addHandler(logging.StreamHandler())
    logging.getLogger().setLevel(logging.INFO)

    import thread
    thread.start_new_thread(Task.objects.scheduler, ())
