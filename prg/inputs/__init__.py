import Queue
import threading

import schedule
import time
from config import LocalSettings

from graphitereporter import *


__myclasses__ = {}

__logger__ = logging.getLogger("inputs")
__logger__.setLevel(logging.INFO)


def __load_receiver__(elem, config):
    if elem not in __myclasses__:
        __logger__.info("Loading input of type %s" % elem)
        mod = __import__(elem, globals=globals())
        __myclasses__[elem] = getattr(mod, elem)
        if hasattr(mod, 'init'):
            getattr(mod, 'init')(config)
            __logger__.info("Initializing %s" % elem)

    return __myclasses__[elem]

def init(automation_context):
    inputs = automation_context.config.inputs()
    instantiatedInputs = Inputs(automation_context)
    for name in inputs:
        my_class = __load_receiver__(inputs[name]['type'], automation_context.config)
        instantiatedInputs.addInput(my_class(name, automation_context, LocalSettings(inputs[name])))

    return instantiatedInputs


class Inputs(object):
    """
    Simple parent wrapper for all Inputs that are defined
    """
    def __init__(self, automation_context):
        '''
        @type automation_context: context.AutomationContext
        '''
        self.inputs = {}
        self.automation_context = automation_context


    def addInput(self, input):
        """
        @type input: inputs.AnInput
        """
        self.inputs[input.name] = input

    def refreshAll(self):
        """
        Any input that has a refresh method (for instance subclasses of PollingInput, get refreshed at this point
        """
        [self.automation_context.async_perform(input.refresh) for input in self.inputs.values() if hasattr(input, 'refresh')]

    def start(self):
        [input.start() for input in self.inputs.values()]

        self.refreshAll()
        self.schedule = schedule.every(10).seconds.do(self.refreshAll)
        __logger__.info("Inputs started")

    def stop(self):
        schedule.cancel_job(self.schedule)

        [input.stop() for input in self.inputs.values()]
        __logger__.info("Inputs stopped")

    def __getitem__(self, key):
        return self.inputs[key]

    def __worker_main__(self):
        while True:
            self.jobqueue.get()()

