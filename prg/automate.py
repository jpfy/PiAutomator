#!/usr/bin/python

import os, time, dhtreader, sys, signal, receivers, inputs, schedule,logging, rules
from receivers import receiver
from timeout import timeout, TimeoutError
from graphitereporter import GraphiteReporter
from config import AutomationConfig

logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(message)s')
basedir = os.path.normpath("%s/.." % (os.path.dirname(os.path.abspath(__file__))))
config = AutomationConfig(basedir)

receivers = receivers.init(config)
inputs = inputs.init(config)
rules = rules.init(config)

global running
running = True
def signal_handler(signal, frame):
  global running
  running = False
  print 'Terminating'

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def checkrules():
  rules.findMatchingRules(inputs).andPerformTheirActions(receivers)

schedule.every(5).seconds.do(checkrules)

# Continuously append data
while(running):
  schedule.run_pending()
  time.sleep(1)