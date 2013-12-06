from receivers import *
import Queue, threading, logging, subprocess

jobqueue = Queue.Queue()

__logger__ = logging.getLogger("tool-command-receiver")

def init(config):
  def __worker_main__():
    while True:
      toexec = jobqueue.get()
      __logger__.info(toexec)
      subprocess.call(toexec, shell=True)

  worker_thread = threading.Thread(target=__worker_main__)
  worker_thread.daemon = True
  worker_thread.start()

class ToolCommandReceiver(Receiver):
  def __init__(self, name, config, settings, g):
    super(ToolCommandReceiver, self).__init__(name, config, settings, g)
    self.intools = not ('intools' in settings and not settings['intools'])

  def _setState(self, state):
    command = None
    if self.intools:
      command = "%s/tools/%s" % (self.config.get_basedir(), self.settings['command'])
    else:
      command = self.settings['command']
    args = self.settings['args'].replace("${state}", state).replace("${name}", self.name)
    toexec = "%s %s" % (command, args)
    jobqueue.put(toexec)
