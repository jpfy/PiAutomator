#!/usr/bin/python
import yaml


class AutomationConfig(object):
    def __init__(self, basedir):
        self.basedir = basedir
        with open("%s/conf/config.yaml" % basedir) as f:
            self.yaml = yaml.load(f)

    def getSetting(self, mapList, default=None):
        try:
            return reduce(lambda d, k: d[k], mapList, self.yaml)
        except KeyError as e:
            if default:
                return default
            else:
                raise e

    def inputs(self):
        return self.getSetting(['inputs'])

    def receivers(self):
        return self.getSetting(['receivers'])

    def rules(self):
        return self.getSetting(['rules'])

    def get_basedir(self):
        return self.basedir

