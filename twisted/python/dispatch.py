# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.

import warnings
warnings.warn(
    "Create your own event dispatching mechanism, "
    "twisted.python.dispatch will soon be no more.",
    DeprecationWarning, 2)

class EventDispatcher(object):
    __slots__ = [
        '_handlers']

    def __init__(self):
        self._handlers = {}

    @property
    def handlers(self):
        return self._handlers

    @handlers.setter
    def handlers(self, handlers):
        self._handlers = handlers

    def registerHandler(self, name, method):
        if name in self.handlers.keys():
            return

        self.handlers[name] = method

    def autoRegister(self, obj):
        if not obj:
            raise TypeError('Cannot auto register handlers because the object is NULL!')

        for name in obj.keys():
            if name in self.handlers.keys():
                continue

            self.handlers[name] = obj[name]

    def publishEvent(self, name, *args, **kwargs):
        if name not in self.handlers.keys():
            raise AttributeError('Cannot publish event "%s" because it wasn\'t found!' % (
                name,))

        self.handlers[name](*args, **kwargs)
