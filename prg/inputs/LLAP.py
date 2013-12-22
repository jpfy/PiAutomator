"""
This input module supports getting data from pilight (http://http://www.pilight.org/) and triggering rules accordingly
"""
from itertools import dropwhile
from Queue import Queue
import logging
import tempfile
import threading
import re
import serial
import sys
import time
from inputs import AnInput


def _true(value = None):
    return True

def _false(value = None):
    return False

lllap_sensors = {}
__logger__ = logging.getLogger('llap-receiver')
__logger__.setLevel(logging.INFO)

llap_commands = {
    'BATTLOW': ['lowbattery', _true],
    'BATT': ['batterylevel', float],
    'STARTED': ['lowbattery', _false],
    'LVAL': ['lightlevel', float],
    'TEMP': ['temperature', float],
    'TMPA': ['temperature', float],
    'ANA': ['analog', int],
    'BUTTON': ['button', str],
}

llap_hello_cmds = ['HELLO', 'STARTED', 'AWAKE']

global llap_receiver

def init(config):
    """
    Initializes the pilight receiver connection. Sets up a heartbeat

    @type config: config.AutomationConfig
    """
    global llap_receiver

    llap_receiver = LLAPDaemon(
        config.getSetting(['llap','device'], '/dev/ttyAMA0'),
        config.getSetting(['llap','print-debug'], False)
    )

class LLAPCommand(object):
    def __init__(self, device_id, message, wait_for_answer = True):
        self.message = message
        self.wait_for_answer = wait_for_answer
        self.device_id = device_id

    def apply(self):
        __logger__.debug("Sending %s %s", self.device_id, self.message)
        llap_receiver.send(self.device_id, self.message)
        return not self.wait_for_answer

    def has_received_reply(self, sentcommand):
        if sentcommand.startswith("SLEEPING") and self.message.startswith("SLEEP"):
            __logger__.debug("Received %s %s %s", self.device_id, self.message, sentcommand)
            return True
        if sentcommand.startswith(self.message):
            __logger__.debug("Received %s %s %s", self.device_id, self.message, sentcommand)
            return True
        return False

class LLAP(AnInput):
    def __init__(self,  name, context, settings):
        super(LLAP, self).__init__(name, context, settings)
        self.device_id = settings['device-id']
        self.values = None
        self.cycle = settings.getsetting('cycle', False)
        self.cycle_period = settings.getsetting('cycle-period', '005S')
        self.read_command = settings.getsetting('read-command', 'TEMP')
        self.command_queue = []
        self.inflight = False
        lllap_sensors[self.device_id] = self

    def cycle_hello(self, sentcommand):
        if self.cycle:
            for command in llap_hello_cmds:
                if sentcommand.startswith(command):
                    self.command_queue = []
                    self.send(self.read_command)
                    self.send("BATT")
                    self.send("SLEEP" + self.cycle_period)

    def process_incomming(self, sentcommand):
        for command in sorted(llap_commands, key=lambda x: len(x), reverse=True):
            if sentcommand.startswith(command):
                value = sentcommand[len(command):]
                key = llap_commands[command][0]
                converter = llap_commands[command][1]
                self.publish({key: converter(value)})
                break

    def process_queue(self, sentcommand = "YEAHWHATEVER"):
        if self.inflight and self.i_received_reply(sentcommand):
            self.command_queue.pop(0)
            self.inflight = False

        if not self.inflight:
            self.send_what_you_can()

    def update(self, sentcommand):
        if not self.started: return
        __logger__.debug("update: " + sentcommand)
        self.cycle_hello(sentcommand)
        self.process_incomming(sentcommand)
        self.process_queue(sentcommand)

    def send(self, message, wait_for_it = True):
        self.command_queue.append(LLAPCommand(self.device_id, message, wait_for_it))

    def start(self):
        super(LLAP, self).start()
        if self.cycle:
            # Say hello, should get a response from the other end
            self.send("HELLO", False)
            self.process_queue()

    def send_what_you_can(self):
        while self.send_one():
            pass

    def send_one(self):
        if len(self.command_queue) > 0:
            cmd = self.command_queue[0]
            if cmd.apply():
                self.command_queue.pop(0)
                return True
            else:
                self.inflight = True
                return False

    def i_received_reply(self, sentcommand):
        return self.command_queue[0].has_received_reply(sentcommand)


class LLAPDaemon(object):
    def __init__(self, device, debug):
        self.p = re.compile('a[A-Z][A-Z][A-Z0-9.-]{9,}.*')
        self.ser = serial.Serial(device, 9600)
        self.debug = debug
        self.current_buffer = ""
        if (debug):
            self.debug_file = tempfile.NamedTemporaryFile()
            __logger__.info("Debugging serial input to %s", self.debug_file.name)
            self.debug_file.write("----- Serial input debug file -----\n")
            self.debug_file.flush()

        self.inwaiting = {}
        self.inwaiting_times = {}
        self.send_queue = Queue()
        thread = threading.Thread(target=self.receive)
        thread.daemon = True
        thread.start()
        thread = threading.Thread(target=self.__send__)
        thread.daemon = True
        thread.start()


    def send(self, device, message):
        self.send_queue.put(
            {
                'device': device,
                'message': message,
                'time': time.time() * 1000
            }
        )

    def __send__(self):
        def is_enough_time_passed_for_message(msg):
            message_time = msg['time']
            device = msg['device']
            device_time = message_time
            if device in self.inwaiting_times:
                device_time = self.inwaiting_times[device]
            device_time = max(message_time, device_time)
            current_time = time.time() * 1000
            return current_time - device_time > 1


        while True:
            msg = self.send_queue.get()
            try:
                device = msg['device']
                message = msg['message']
                if device in self.inwaiting and msg is not self.inwaiting[device]:
                    self.send_queue.put(msg)
                elif is_enough_time_passed_for_message(msg):
                    if device in self.inwaiting:
                        del self.inwaiting[device]
                    __logger__.debug("Sending: %s", msg)
                    llap_message = ('a' + device + message).ljust(12, '-')
                    self.ser.write(llap_message)
                    self.inwaiting_times[device] = time.time() * 1000
                    if self.debug:
                        # Nice thing about tmp files is that Python will clean them on
                        # system close
                        self.debug_file.write(llap_message)
                        self.debug_file.flush()
                    # Wait some time, since command that go too quick seem to be a problem
                else:
                    __logger__.debug("Waiting: %s", msg)
                    self.inwaiting[device] = msg
                    self.send_queue.put(msg)
            except:
                __logger__.exception(sys.exc_info()[0])
                __logger__.warn("exception happened")

    def receive(self):
        __logger__.info("Starting in receiving mode for llap")
        try:
            while True:
                self.current_buffer += self.__read__(1)
                n = self.ser.inWaiting()
                if (n > 0):
                    self.current_buffer += self.__read__(n)
                self.find_messages()
        except:
            __logger__.exception(sys.exc_info()[0])
            __logger__.warn("exception happened")

    def __read__(self, size):
        result = self.ser.read(size)
        if self.debug:
            # Nice thing about tmp files is that Python will clean them on
            # system close
            self.debug_file.write(result)
            self.debug_file.flush()
        return result

    def find_messages(self):
        try:
            self.current_buffer = ''.join(dropwhile(lambda x: not x == 'a', (i for i in self.current_buffer)))
            if len(self.current_buffer) >= 12:  # 12 is the LLAP message length
                 if self.p.match(self.current_buffer):
                     self.process_device_message(self.current_buffer[0:12])
                     self.current_buffer = self.current_buffer[12:]
                 else:
                     self.current_buffer = self.current_buffer[1:]
                     self.find_messages()
        except:
            __logger__.exception(sys.exc_info()[0])
            __logger__.warn("exception happened")

    def process_device_message(self, message):
        device = message[1:3]
        command = message[3:].replace('-','')
        if command.startswith("CHDEVID"):
            __logger__.info("We were asked to change our device id, but we're only listening:), %s", command)
        elif device in lllap_sensors:
            llap_sensor = lllap_sensors[device]
            llap_sensor.update(command)