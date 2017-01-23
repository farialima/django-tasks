#
# Copyright (c) 2010 by nexB, Inc. http://www.nexb.com/ - All rights reserved.
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


#
# Public API to use DjangoTasks.
#
# The functions below should be sufficient to work with djangotasks.
# Please enter bugs on https://github.com/farialima/django-tasks/ if you need anything more.
#
#

def task(*methods_or_functions):
    ''' Decorator to transform a function, or a model method, into a task.
    
    Once decorated with @task, the function can only run as an asynchronous task.
    It returns a Task object that can be run (asynchronously), by calling its run() method.

    The method or function must have no parameters, as they would not be passed to the task;
    and they should not return anything, since the return value would be lost.

    see djangotasks.models.Task for more information about the Task object.
    '''

    if hasattr(methods_or_functions[0], 'wrapped_method_or_function'): 
        # The first argument is already a task, so it must be a dependent;
        # it means that the annotation was called with parameters.
        # So we return the annotation itself, but with the dependents already set.
        def partial_task(the_method):
            return task(the_method, *methods_or_functions)
        return partial_task

    method_or_function = methods_or_functions[0]
    dependents = methods_or_functions[1:] or None

    def return_task(instance=None):
        from djangotasks.models import Task
        if instance:
            return Task.objects.task_for_object(instance, method_or_function, dependents)
        else:
            return Task.objects.task_for_function(method_or_function, dependents)

    return_task.wrapped_method_or_function = method_or_function
    return return_task

def current_task():
    '''The task being executed. 

    Only available in the process that's executing a task; None in all other cases.'''
    from djangotasks.models import Task
    return Task.objects.current_task
