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

from __future__ import with_statement 

import sys
import StringIO
import os
import unittest
import tempfile
import time
import inspect
import logging
from os.path import join, dirname, basename, exists, join

import re
DATETIME_REGEX = re.compile('([a-zA-Z]+[.]? \d+\, \d\d\d\d at \d+(\:\d+)? [ap]\.m\. [A-Z]{1,5})|( \((\d+ hour(s)?(, )?)?(\d+ minute(s)?(, )?)?(\d+ second(s)?(, )?)?\))')

from django.db import models

import djangotasks
from djangotasks import task

from djangotasks.models import Task

class LogCheck(object):
    def __init__(self, test, expected_log = None, fail_if_different=True):
        self.test = test
        self.expected_log = expected_log or ''
        self.fail_if_different = fail_if_different
        
    def __enter__(self):
        from djangotasks.models import LOG
        self.loghandlers = LOG.handlers
        LOG.handlers = []
        self.log = StringIO.StringIO()
        test_handler = logging.StreamHandler(self.log)
        test_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        self.loglevel = LOG.getEffectiveLevel()
        LOG.setLevel(logging.INFO)
        LOG.addHandler(test_handler)
        
    def __exit__(self, type, value, traceback):
        # Restore state
        from djangotasks.models import LOG
        LOG.handlers = self.loghandlers
        LOG.setLevel(self.loglevel)

        # Check the output only if no exception occured (to avoid "eating" test failures)
        if type:
            return
        
        if self.fail_if_different:
            self.test.assertEquals(self.expected_log, self.log.getvalue())

class TestModel(models.Model):

    key = models.CharField(
        unique=True,
        primary_key=True,
        max_length = 90,
    )


    def _run(self, trigger_name, sleep=0.2):
        print "running %s" % trigger_name
        sys.stdout.flush()
        time.sleep(sleep)
        self._trigger(trigger_name)

    @task
    def run_something_long(self):        
        self._run("run_something_long_1", 0.0) # trigger right away, 
        time.sleep(0.2) # then sleep
        self._run("run_something_long_2")
        return "finished"
    
    @task
    def run_something_else(self):
        pass

    @task
    def run_something_failing(self):
        self._run("run_something_failing")
        raise Exception("Failed !")

    @task(run_something_long)
    def run_something_with_dependent(self):
        self._run("run_something_with_dependent")
        return "finished dependent"

    @task(run_something_failing)
    def run_something_with_dependent_failing(self):
        self._run("run_something_with_dependent")
        return "finished dependent"

    @task(run_something_long, run_something_with_dependent)
    def run_something_with_two_dependent(self):
        self._run("run_something_with_two_dependent")
        return "finished run_something_with_two_dependent"

    @task(run_something_with_two_dependent)
    def run_something_with_dependent_with_two_dependent(self):
        self._run("run_something_with_dependent_with_two_dependent")
        return "finished dependent with dependent"

    def run_a_method_that_is_not_registered(self):
        self.fail("should not be called in the tests")

    @task
    def run_something_fast(self):
        self._run("run_something_fast", 0.1)

    @task
    def check_database_settings(self):
        from django.db import connection
        print connection.settings_dict["NAME"]
        time.sleep(0.1)
        self._trigger("check_database_settings")

    @task
    def run_method_with_parameter_should_fail(self, some_parameter):        
        self.fail("should fail before being executed")
    
    def _trigger(self, event):
        open(self.pk + event, 'w').writelines(["."])

def _start_message(task):
    return "INFO: Starting task " + str(task.pk) + "...\nINFO: ...Task " + str(task.pk) + " started.\n" 
    

@task
def _test_function():
    print "running _test_function"

@task(_test_function)
def _test_function_with_dependent():
    print "running _test_function_with_dependent"

def _some_function():
    print "running _some_function"

class TasksTestCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tempdir = tempfile.mkdtemp()
        import os
        os.environ['DJANGOTASKS_TESTING'] = "YES"

    def tearDown(self):
        from djangotasks.models import TaskManager
        keep_database = any(param in sys.argv for param in ['-k', '--keepdb'])
        if not keep_database:
            for task in Task.objects.filter(model='djangotasks.testmodel'):
                task.delete()
        import shutil
        shutil.rmtree(self.tempdir)
        import os
        del os.environ['DJANGOTASKS_TESTING']
        
    #  This may be needed for databases that can't share transactions (connections) accross threads (sqlite in particular):
    #  the tests tasks may need to be commited before the execution thread is started, which require transaction.commit to actually *do* the commit --
    #  and the original "_fixture_setup" causes "transaction.commit" to be transformed into a "nop" !!!
    #def _fixture_setup(self):
    #    pass
    #def _fixture_teardown(self):
    #    pass

    def _wait_until(self, key, event):
        max = 10 # in seconds
        while not exists(join(self.tempdir, key + event)) and max >= 0:
            time.sleep(0.1)
            max -= 0.1
        if max < 0:
            self.fail("Timeout on key=%s, event=%s" % (key, event))
        
    def _reset(self, key, event):
        os.remove(join(self.tempdir, key + event))

    def _assert_status(self, expected_status, task):
        task = Task.objects.get(pk=task.pk)
        self.assertEquals(expected_status, task.status)

    def _check_running(self, key, current_task, previous_task, task_name, expected_log=None):
        self._assert_status("scheduled", current_task)
        with LogCheck(self, _start_message(current_task)):        
            Task.objects._do_schedule()
        time.sleep(0.1)
        self._assert_status("running", current_task)
        if previous_task:
            self._assert_status("successful", previous_task)
        self._wait_until(key, task_name)
        time.sleep(0.5)
        self._assert_status("successful", current_task)
        if expected_log != None:
            self.assertEquals(expected_log, 
                              Task.objects.get(pk=current_task.pk).log)

    def _create_object_and_test_task(self, method_name, object_id):
        key = join(self.tempdir, object_id)
        object, _ = TestModel.objects.get_or_create(pk=key)
        return getattr(object, method_name)()

    def test_run_function_task(self):
        task = _test_function()
        task = task.run()
        self.assertEquals("scheduled", task.status)
        with LogCheck(self, _start_message(task)):
            Task.objects._do_schedule()
        i = 0
        while i < 100: # 20 seconds should be enough
            i += 1
            time.sleep(0.2)
            task = Task.objects.get(pk=task.pk)
            if task.status == "successful":
                break

        self.assertEquals("successful", task.status)
        self.assertEquals("running _test_function\n", task.log)
        
    def test_tasks_run_successful(self):
        task = self._create_object_and_test_task('run_something_long', 'key1')
        task.run()
        self._check_running('key1', task, None, 'run_something_long_2',
                            u'running run_something_long_1\nrunning run_something_long_2\n')

    def test__to_function_name(self):
        from djangotasks.models import _to_function_name
        self.assertEquals('djangotasks.tests._some_function', _to_function_name(_some_function))

    def test__to_function(self):
        from djangotasks.models import _to_function
        self.assertEquals(_some_function, _to_function('djangotasks.tests._some_function'))

    def test__get_model_class(self):
        from djangotasks.models import _get_model_class
        self.assertEquals(TestModel, _get_model_class('djangotasks.testmodel'))

    def test__get_model_name(self):
        from djangotasks.models import _get_model_name
        self.assertEquals('djangotasks.testmodel', _get_model_name(TestModel))

    def test_task_on_non_model(self):
        test = self
        class NotAValidModel(object):
            @task
            def a_method(self):
                test.fail("Should not be called")

        o = NotAValidModel()
        with self.assertRaises(AttributeError) as context:
            the_task = o.a_method()

        self.assertEquals("'NotAValidModel' object has no attribute 'pk'", 
                          context.exception.message)

    def test_task_on_method_with_parameter(self):
        with self.assertRaises(Exception) as context:            
            task = self._create_object_and_test_task('run_method_with_parameter_should_fail', 'key')
            
        self.assertEquals("Cannot use tasks on a method that has parameters", 
                          context.exception.message)
            

    def test_task_on_function_with_parameter(self):
        @task
        def a_function(some_parameter):
            self.fail("Should not be called")
        
        with self.assertRaises(AttributeError) as context:
            the_task = a_function(11)
            self.assertEquals("'int' object has no attribute 'pk'",
                              context.exception.message)

    def test_tasks_run_with_space_fast(self):
        task = self._create_object_and_test_task('run_something_fast', 'key with space')
        task.run()
        self._check_running('key with space', task, None, 'run_something_fast', 
                            u'running run_something_fast\n')

    def test_tasks_run_cancel_running(self):
        task = self._create_object_and_test_task('run_something_long', 'key1')
        task.run()
        with LogCheck(self, _start_message(task)):
            Task.objects._do_schedule()
        self._wait_until('key1', "run_something_long_1")
        task.cancel()
        output_check = LogCheck(self, fail_if_different=False)
        with output_check:
            Task.objects._do_schedule()
            time.sleep(0.3)
        self.assertTrue(("Cancelling task " + str(task.pk) + "...") in output_check.log.getvalue())
        self.assertTrue("cancelled.\n" in output_check.log.getvalue())
        #self.assertTrue('INFO: failed to mark tasked as finished, from status "running" to "unsuccessful" for task 3. May have been finished in a different thread already.\n'
        #                in output_check.log.getvalue())

        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("cancelled", new_task.status)
        self.assertTrue(u'running run_something_long_1' in new_task.log)
        self.assertFalse(u'running run_something_long_2' in new_task.log)
        self.assertFalse('finished' in new_task.log)

    def test_tasks_run_cancel_scheduled(self):
        task = self._create_object_and_test_task('run_something_long', 'key1')
        with LogCheck(self):
            Task.objects._do_schedule()
        task.run()
        task.cancel()
        with LogCheck(self, "INFO: Cancelling task " + str(task.pk) + "...\nINFO: Task " + str(task.pk) + " finished with status \"cancelled\"\nINFO: ...Task " + str(task.pk) + " cancelled.\n"):
            Task.objects._do_schedule()
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("cancelled", new_task.status)            
        self.assertEquals("", new_task.log)

    def test_tasks_run_failing(self):
        task = self._create_object_and_test_task('run_something_failing', 'key1')
        task.run()
        with LogCheck(self, _start_message(task)):
            Task.objects._do_schedule()
        self._wait_until('key1', "run_something_failing")
        time.sleep(0.5)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("unsuccessful", new_task.status)
        self.assertTrue(u'running run_something_failing' in new_task.log)
        self.assertTrue(u'raise Exception("Failed !")' in new_task.log)
        self.assertTrue(u'Exception: Failed !' in new_task.log)
    
    def test_tasks_get_task_for_object(self):
        task = self._create_object_and_test_task('run_something_long', 'key2')
        self.assertEquals('defined', task.status)
        self.assertEquals('run_something_long', task.method)

    def test_tasks_exception_in_thread(self):
        task = self._create_object_and_test_task('run_something_long', 'key1')
        task.run()
        task = self._create_object_and_test_task('run_something_long', 'key1')
        task_delete = self._create_object_and_test_task('run_something_long', 'key1')
        task_delete.delete()
        try:
            Task.objects.get(pk=task.pk)
            self.fail("Should throw an exception")
        except Exception, e:
            self.assertEquals("Task matching query does not exist.", str(e))
            
        with LogCheck(self, 'WARNING: Failed to change status from "scheduled" to "running" for task %d\n' % task.pk):
            task.do_run()
            time.sleep(0.5)

    def test_MultipleObjectsReturned_in_tasks(self):
        task = self._create_object_and_test_task('run_something_long', 'key1')
        task.pk = None
        super(Task, task).save()
        task = self._create_object_and_test_task('run_something_long', 'key1')

    def test_send_signal_on_task_completed(self):
        from djangotasks.models import TaskManager
        from djangotasks.signals import task_completed
        
        def receiver(sender, **kwargs):
            task = kwargs['task']
            self.assertEqual(TaskManager, sender.__class__)
            self.assertEqual(Task, task.__class__)
            self.assertEqual(TestModel, kwargs['object'].__class__)
            self.assertEqual('successful', task.status)
            # Ensure that this function was called by the Signal
            task.log = "Text added from the signal receiver"
            task.save()
        
        task_completed.connect(receiver)
        task = self._create_object_and_test_task('run_something_fast', 'key1')
        task.run()
        self._check_running('key1', task, None, 'run_something_fast',
                            u'Text added from the signal receiver')
        task_completed.disconnect()


    def test_compute_duration(self):
        from datetime import datetime
        from datetime import timedelta, tzinfo

        ZERO = timedelta(0)

        class UTC(tzinfo):
            def utcoffset(self, dt):
                return ZERO
            def tzname(self, dt):
                return "UTC"
            def dst(self, dt):
                return ZERO

        utc = UTC()

        task = Task.objects._task_for_object(TestModel, 'key1', 'run_something_fast', None)
        task.start_date = datetime(2010, 10, 7, 14, 22, 17, 848801, tzinfo=utc)
        task.end_date = datetime(2010, 10, 7, 17, 23, 43, 933740, tzinfo=utc)
        self.assertEquals('3 hours, 1 minute, 26 seconds', task.duration)
        task.end_date = datetime(2010, 10, 7, 15, 12, 18, 933740, tzinfo=utc)
        self.assertEquals('50 minutes, 1 second', task.duration)
        task.end_date = datetime(2010, 10, 7, 15, 22, 49, 933740, tzinfo=utc)
        self.assertEquals('1 hour, 32 seconds', task.duration)
        task.end_date = datetime(2010, 10, 7, 14, 22, 55, 933740, tzinfo=utc)
        self.assertEquals('38 seconds', task.duration)

    def test_tasks_run_check_database(self):
        task = self._create_object_and_test_task('check_database_settings', 'key1')
        task.run()
        from django.db import connection
        self._check_running('key1', task, None, 'check_database_settings', 
                            connection.settings_dict["NAME"] + u'\n') # May fail if your Django settings define a different test database for each run: in which case you should modify it, to ensure it's always the same.

    def test_tasks_archive_task(self):
        task = Task.objects._task_for_object(TestModel, 'key1', 'run_something_fast', None)
        self.assertTrue(task.pk)
        task.status = 'successful'
        task.save()
        self.assertEquals(False, task.archived)
        new_task = task.run()
        
        self.assertTrue(new_task.pk)
        self.assertTrue(task.pk != new_task.pk)
        old_task = Task.objects.get(pk=task.pk)
        self.assertEquals(True, old_task.archived, "Task should have been archived once a new one has been created")
        self.assertEquals(1, len(task.archives()))
        
    def test_tasks_run_again(self):
        task = self._create_object_and_test_task('run_something_fast', 'key1')
        task.run()
        with LogCheck(self, _start_message(task)):
            Task.objects._do_schedule()
        self._wait_until('key1', "run_something_fast")

        time.sleep(0.5)
        self._reset('key1', "run_something_fast")
        self._assert_status("successful", task)
        
        task = self._create_object_and_test_task('run_something_fast', 'key1')
        task.run()
        output_check = LogCheck(self, fail_if_different=False)
        with output_check:
            Task.objects._do_schedule()
        self._wait_until('key1', "run_something_fast")
        time.sleep(0.5)
        import re
        pks = re.findall(r'(\d+)', output_check.log.getvalue())
        new_task = Task.objects.get(pk=int(pks[0]))
        self.assertEquals(_start_message(new_task)
                          # TODO: this should be logged, and is not... this is very strange
                          # since the task is marked as successful in the DB
                          #+ 'INFO: Task ' + str(new_task.pk) + ' finished with status "successful"\n'
                          , 
                          output_check.log.getvalue())
        self.assertTrue(new_task.pk != task.pk)
        self.assertEquals("successful", new_task.status)
        self.assertEquals(1, len(new_task.archives()))
        
    def test_tasks_get_dependent_tasks(self):
        task = self._create_object_and_test_task('run_something_with_dependent', 'key1')
        self.assertEquals(['run_something_long'],
                          [dependent_task.method for dependent_task in task.get_dependent_tasks()])
        
    def test_tasks_get_dependent_tasks_two_dependent(self):
        task = self._create_object_and_test_task('run_something_with_two_dependent', 'key1')
        self.assertEquals(['run_something_long', 'run_something_with_dependent'],
                          [dependent_task.method for dependent_task in task.get_dependent_tasks()])

    def test_tasks_run_dependent_task_successful(self):
        dependent_task = self._create_object_and_test_task('run_something_long', 'key1')
        task = self._create_object_and_test_task('run_something_with_dependent', 'key1')
        self.assertEquals("defined", dependent_task.status)

        task.run()
        self._assert_status("scheduled", task)
        self._assert_status("scheduled", dependent_task)

        self._check_running('key1', dependent_task, None, 'run_something_long_2')
        self._check_running('key1', task, dependent_task, 'run_something_with_dependent')

        task = Task.objects.get(pk=task.pk)
        complete_log, _ = DATETIME_REGEX.subn('', task.complete_log())

        self.assertEquals(u'djangotasks.testmodel.run_something_long(pk = %s/key1) started on \n' % self.tempdir + 
                          u'running run_something_long_1\n' + 
                          u'running run_something_long_2\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_long(pk = %s/key1) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key1) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key1) finished successfully on ' % self.tempdir, 
                          complete_log)

        complete_log_direct, _ = DATETIME_REGEX.subn('', task.complete_log(True))

        self.assertEquals(u'djangotasks.testmodel.run_something_long(pk = %s/key1) started on \n' % self.tempdir + 
                          u'running run_something_long_1\n' + 
                          u'running run_something_long_2\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_long(pk = %s/key1) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key1) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key1) finished successfully on ' % self.tempdir, 
                          complete_log_direct)

    def test_tasks_run_two_dependent_tasks_successful(self):
        key = 'key2'
        dependent_task = self._create_object_and_test_task('run_something_long', key)
        with_dependent_task = self._create_object_and_test_task('run_something_with_dependent', key)
        task = self._create_object_and_test_task('run_something_with_two_dependent', key)
        self.assertEquals("defined", dependent_task.status)

        task.run()
        self._assert_status("scheduled", task)
        self._assert_status("scheduled", dependent_task)

        self._check_running(key, dependent_task, None, 'run_something_long_2')
        self._check_running(key, with_dependent_task, dependent_task, 'run_something_with_dependent')
        self._check_running(key, task, with_dependent_task, 'run_something_with_two_dependent')

        task = Task.objects.get(pk=task.pk)
        complete_log, _ = DATETIME_REGEX.subn('', task.complete_log())

        self.assertEquals(u'djangotasks.testmodel.run_something_long(pk = %s/key2) started on \n' % self.tempdir + 
                          u'running run_something_long_1\n' + 
                          u'running run_something_long_2\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_long(pk = %s/key2) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key2) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key2) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key2) started on \n' % self.tempdir + 
                          u'running run_something_with_two_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key2) finished successfully on ' % self.tempdir,
                          complete_log)

        complete_log_direct, _ = DATETIME_REGEX.subn('', task.complete_log(True))

        self.assertEquals(u'djangotasks.testmodel.run_something_long(pk = %s/key2) started on \n' % self.tempdir + 
                          u'running run_something_long_1\n' + 
                          u'running run_something_long_2\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_long(pk = %s/key2) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key2) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key2) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key2) started on \n' % self.tempdir + 
                          u'running run_something_with_two_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key2) finished successfully on ' % self.tempdir,
                          complete_log_direct)

    def test_tasks_run_dependent_with_two_dependent_tasks_successful(self):
        key = 'key3'
        dependent_task = self._create_object_and_test_task('run_something_long', key)
        with_dependent_task = self._create_object_and_test_task('run_something_with_dependent', key)
        with_two_dependent_task = self._create_object_and_test_task('run_something_with_two_dependent', key)
        task = self._create_object_and_test_task('run_something_with_dependent_with_two_dependent', key)
        self.assertEquals("defined", dependent_task.status)

        task.run()

        self._assert_status("scheduled", task)
        self._assert_status("scheduled", with_dependent_task)
        self._assert_status("scheduled", with_two_dependent_task)
        self._assert_status("scheduled", dependent_task)

        self._check_running(key, dependent_task, None, 'run_something_long_2')
        self._check_running(key, with_dependent_task, dependent_task, "run_something_with_dependent")
        self._check_running(key, with_two_dependent_task, with_dependent_task, "run_something_with_two_dependent")
        self._check_running(key, task, with_two_dependent_task, "run_something_with_dependent_with_two_dependent")

        task = Task.objects.get(pk=task.pk)
        complete_log, _ = DATETIME_REGEX.subn('', task.complete_log())

        self.assertEquals(u'djangotasks.testmodel.run_something_long(pk = %s/key3) started on \n' % self.tempdir + 
                          u'running run_something_long_1\n' + 
                          u'running run_something_long_2\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_long(pk = %s/key3) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key3) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent(pk = %s/key3) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key3) started on \n' % self.tempdir + 
                          u'running run_something_with_two_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key3) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent_with_two_dependent(pk = %s/key3) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent_with_two_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent_with_two_dependent(pk = %s/key3) finished successfully on ' % self.tempdir,
                          complete_log)

        complete_log_direct, _ = DATETIME_REGEX.subn('', task.complete_log(True))

        self.assertEquals(u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key3) started on \n' % self.tempdir + 
                          u'running run_something_with_two_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_two_dependent(pk = %s/key3) finished successfully on \n' % self.tempdir + 
                          u'djangotasks.testmodel.run_something_with_dependent_with_two_dependent(pk = %s/key3) started on \n' % self.tempdir + 
                          u'running run_something_with_dependent_with_two_dependent\n' + 
                          u'\n' + 
                          u'djangotasks.testmodel.run_something_with_dependent_with_two_dependent(pk = %s/key3) finished successfully on ' % self.tempdir,
                          complete_log_direct)

    def test_tasks_run_dependent_task_failing(self):
        dependent_task = self._create_object_and_test_task('run_something_failing', 'key1')
        task = self._create_object_and_test_task('run_something_with_dependent_failing', 'key1')
        self.assertEquals("defined", dependent_task.status)

        task.run()
        self._assert_status("scheduled", task)
        self._assert_status("scheduled", dependent_task)

        with LogCheck(self, _start_message(dependent_task)):
            Task.objects._do_schedule()
        time.sleep(0.5)
        self._assert_status("scheduled", task)
        self._assert_status("running", dependent_task)

        self._wait_until('key1', 'run_something_failing')
        time.sleep(0.5)
        self._assert_status("scheduled", task)
        self._assert_status("unsuccessful", dependent_task)

        with LogCheck(self):
            Task.objects._do_schedule()
        time.sleep(0.5)
        self._assert_status("unsuccessful", task)
        task = Task.objects.get(pk=task.pk)

        complete_log, _ = DATETIME_REGEX.subn('', task.complete_log())
        self.assertTrue(complete_log.startswith('djangotasks.testmodel.run_something_failing(pk = %s/key1) started on \n' % self.tempdir +
                                                'running run_something_failing\n' + 
                                                'Traceback (most recent call last):\n'))
        self.assertTrue(complete_log.endswith(u', in run_something_failing\n' + 
                                              u'    raise Exception("Failed !")\n' + 
                                              u'Exception: Failed !\n\n' + 
                                              u'djangotasks.testmodel.run_something_failing(pk = %s/key1) failed on \n' % self.tempdir + 
                                              u'djangotasks.testmodel.run_something_with_dependent_failing(pk = %s/key1) started\n' % self.tempdir + 
                                              u'djangotasks.testmodel.run_something_with_dependent_failing(pk = %s/key1) failed' % self.tempdir))
        complete_log_direct, _ = DATETIME_REGEX.subn('', task.complete_log(True))
        self.assertTrue(complete_log_direct.startswith('djangotasks.testmodel.run_something_failing(pk = %s/key1) started on \n' % self.tempdir + 
                                                       u'running run_something_failing\n' + 
                                                       u'Traceback (most recent call last):\n'))
        self.assertTrue(complete_log_direct.endswith(u', in run_something_failing\n' + 
                                                     u'    raise Exception("Failed !")\n' + 
                                                     u'Exception: Failed !\n\n' + 
                                                     u'djangotasks.testmodel.run_something_failing(pk = %s/key1) failed on \n' % self.tempdir + 
                                                     u'djangotasks.testmodel.run_something_with_dependent_failing(pk = %s/key1) started\n' % self.tempdir + 
                                                     u'djangotasks.testmodel.run_something_with_dependent_failing(pk = %s/key1) failed' % self.tempdir))
        self.assertEquals("unsuccessful", task.status)

    def test_run_function_task_with_dependent(self):
        task = _test_function_with_dependent()
        task = task.run()
        self.assertEquals("scheduled", task.status)
        if True: # with LogCheck(self):
            Task.objects._do_schedule()
        time.sleep(0.5)
        with LogCheck(self):
            Task.objects._do_schedule()
        time.sleep(0.5)
        with LogCheck(self):
            Task.objects._do_schedule()
        i = 0
        while i < 100: # 20 seconds should be enough
            i += 1
            time.sleep(0.2)
            task = Task.objects.get(pk=task.pk)
            if task.status == "successful":
                break

        self.assertEquals("successful", task.status)
        self.assertEquals("running _test_function_with_dependent\n", task.log)
        complete_log, _ = DATETIME_REGEX.subn('', task.complete_log(True))
        self.assertEquals(u'djangotasks.functiontask.run_function_task(pk = djangotasks.tests._test_function) started on \n' + 
                          u'running _test_function\n\n' + 
                          u'djangotasks.functiontask.run_function_task(pk = djangotasks.tests._test_function) finished successfully on \n' + 
                          u'djangotasks.functiontask.run_function_task(pk = djangotasks.tests._test_function_with_dependent) started on \n' + 
                          u'running _test_function_with_dependent\n\n' +
                          u'djangotasks.functiontask.run_function_task(pk = djangotasks.tests._test_function_with_dependent) finished successfully on ', complete_log)
        
