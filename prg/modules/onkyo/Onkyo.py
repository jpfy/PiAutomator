import logging
import socket
import struct
import threading
import time
from inputs.inputs import AnInput

class converter(object):
    def to(self, input):
        pass

    def frm(self, input):
        pass

class dict_converter(converter):
    def __init__(self, data):
        self.data = data

    def to(self, input):
        return self.data[input]

    def frm(self, input):
        for elem in self.data.items():
            if elem[1] == input:
                return elem[0]


class hex_converter(converter):
    def to(self, input):
        return int('0x' + input, 16)

    def frm(self, input):
        hex(input)[2:]



converters = {
    'onoff': dict_converter({
        '01': 'on',
        '00': 'off',
        'N/A': 'not-applicable'
    }),
    'inputs': dict_converter({
        "00":"VIDEO1",
        "01":"VIDEO2",
        "02":"VIDEO3",
        "03":"VIDEO4",
        "04":"VIDEO5",
        "05":"VIDEO6",
        "06":"VIDEO7",
        "07":"Hidden1",
        "08":"Hidden2",
        "09":"Hidden3",
        "10":"BD-DVD",
        "20":"TV-TAPE",
        "21":"TAPE2",
        "22":"PHONO",
        "23":"TV-CD",
        "24":"FM",
        "25":"AM",
        "26":"TUNER",
        "27":"MUSIC SERVER",
        "28":"INTERNET RADIO",
        "29":"USB-USB-Front",
        "2A":"USB-Rear",
        "2B":"Net",
        "40":"Universal-PORT",
        "30":"MULTI-CH",
        "31":"XM1",
        "32":"SIRIUS1"
    }),
    'spl': dict_converter({
      "SB": "SurrBack",
      "FH": "FrontHigh",
      "FW": "FrontWide",
      "HW": "FrontHighWide"
    }),
    'hex': hex_converter()
}

def s(name, converter):
    return {'name': name, 'converter': converters[converter]}

onkyo_commands = {
    'PWR': s("power", "onoff"),
    'AMT': s("audio_mute", "onoff"),
    'SPA': s("speaker_a", "onoff"),
    'SPB': s("speaker_b", "onoff"),
    'SPL': s("speaker_layout", "spl"),
    'MVL': s("master_volume", "hex"),
    'SLI': s("selected_input", "inputs")
}


__logger__ = logging.getLogger("onkyo-input")
__logger__.setLevel(logging.INFO)

class Onkyo(AnInput):
    def __init__(self, name, context, settings):
        super(Onkyo, self).__init__(name, context, settings)
        self.s = None
        self.buffer = ""

    def start(self):
        __logger__.info("Starting")
        super(Onkyo, self).start()
        thread = threading.Thread(target=self.__read__, name='onkyo-client')
        thread.daemon = True
        thread.start()

    def __read__(self):
        while True:
            self.__get_socket__()
            if self.s:
                __logger__.debug("Up")
                self.__read_initial_state()
                self.__read_while_open()
            else:
                __logger__.debug("Down")
                self.__publish__("PWR", "00")
            __logger__.debug("Down")
            time.sleep(1)

    def __get_socket__(self):
        if self.s == None:
            try:
                self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.s.settimeout(2)
                self.s.connect((self.settings.getsetting("ip"), self.settings.getsetting("port", 60128)))
            except:
                self.s = None

        return self.s


    def __create_message__(self, message):
        bmessage = bytearray("!1" + message, "ascii")
        bmessage.append(0x0d)
        bmessage.append(0x0a)
        size = struct.pack('>I', len(bmessage))
        header = bytearray("ISCP", "ascii")
        header.append(0)
        header.append(0)
        header.append(0)
        header.append(16)
        header.extend(size)
        header.append(1)
        header.append(0)
        header.append(0)
        header.append(0)
        header.extend(bmessage)
        return header

    def __send__(self, message):
        self.s.send(self.__create_message__(message))

    def __ask__(self, command):
        self.__send__(command + "QSTN")

    def __read_initial_state(self, some_question = None):
        try:
            if some_question is not None:
                self.__ask__(some_question)
            else:
                for command in onkyo_commands:
                    self.__ask__(command)
        except:
            self.__close_connection__("read_initial")

    def __read_while_open(self):
        retry_count = 0
        in_retry = False

        __logger__.info("Connected, reading while open")

        while self.s is not None:
            try:
                received = self.s.recv(1024)
                in_retry = False
                if received == '':
                    self.__close_connection__("nodata")
                else:
                    self.buffer += received
                    self.__find_and_process__()
            except socket.timeout:
                if in_retry:
                    # we should be getting data now :(
                    self.__close_connection__("retry")
                else:
                    retry_count += 1
                    if retry_count == 20:
                        retry_count = 0
                        in_retry = True
                        self.__read_initial_state("PWR")
            except Exception, exception:
                __logger__.exception(exception)
                self.__close_connection__("exception")

    def __find_and_process__(self):
        headerstart = self.buffer.find("ISCP")
        while headerstart >= 0:
            # drop everything to go to the header:
            self.buffer = self.buffer[headerstart:]
            bufferlen = len(self.buffer)
            if bufferlen> 16:
                # we have a whole header + more
                msg_len = struct.unpack(">I", self.buffer[8:12])[0]
                if bufferlen >= 16 + msg_len:
                    # we have a message
                    msg = self.buffer[16: 16+msg_len]
                    self.buffer = self.buffer[16+msg_len:]
                    self.__process__(msg)

            headerstart = self.buffer.find("ISCP")

        if len(self.buffer) > 10:
            __logger__.debug("dropping %s", self.buffer[0:6])
            self.buffer = self.buffer[6:]

    def __close_connection__(self, reason):
        try:
            self.s.close()
        except:
            pass
        __logger__.debug("Connection closed in %s", reason)
        self.s = None

    def __publish__(self, cmd, value):
        try:
            if cmd in onkyo_commands.keys():
                cmd_ = onkyo_commands[cmd]
                self.publish({cmd_['name']: cmd_['converter'].to(value)})
                self.publish({cmd_['name']+"_raw": value})
                __logger__.debug("%s: %s", cmd_['name'], cmd_['converter'].to(value))
                if cmd == 'PWR' and value == '00':
                    self.__close_connection__("PWR00")
            else:
                self.publish({cmd: value})
                __logger__.info("%s: %s", cmd, value)
        except Exception, e:
            __logger__.error("failed to publish %s -> %s", cmd, value)
            __logger__.exception(e)
            pass

    def __process__(self, msg):
        try:
            if msg.startswith(b"!1"):
                cmd = msg[2:5]
                value = msg[5:msg.index(str(unichr(0x1a)))]
                self.__publish__(cmd, value)
            else:
                __logger__.info('found non message "%s"', msg)
        except Exception, e:
            # Drops the message
            __logger__.exception(e)
            pass
