# -*- test-case-name: twisted.test.test_log -*-
# Twisted, the Framework of Your Internet
# Copyright (C) 2001 Matthew W. Lefkowitz
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Logging and metrics infrastructure.
"""

# System Imports
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO

import sys
import time
import threadable
import failure
import warnings

# Sibling Imports

import context


class ILogContext:
    """Actually, this interface is just a synoym for the dictionary interface,
    but it serves as a key for the default information in a log.

    I do not inherit from Interface because the world is a cruel place.
    """

context.setDefault(ILogContext,
                   {"isError": 0,
                    "system": "-"})

def callWithContext(ctx, func, *args, **kw):
    newCtx = context.get(ILogContext).copy()
    newCtx.update(ctx)
    return context.call({ILogContext: newCtx}, func, *args, **kw)

def callWithLogger(logger, func, *args, **kw):
    """
    Utility method which wraps a function in a try:/except:, logs a failure if
    one occurrs, and uses the system's logPrefix.
    """
    try:
        lp = logger.logPrefix()
    except:
        lp = '(buggy logPrefix method)'
        err(system=lp)
    try:
        callWithContext({"system": lp}, func, *args, **kw)
    except:
        err(system=lp)

def write(stuff):
    """Write some data to the log."""
    warnings.warn("What the hell is wrong with you?", DeprecationWarning)
    msg(str(stuff))

def debug(*stuff,**otherstuff):
    """
    Write some data to the log, indented, so it's easier to
    distinguish from 'normal' output.
    """
    msg(debug=1, *stuff, **otherstuff)

def showwarning(message, category, filename, lineno, file=None):
    if file is None:
        msg(warning=message, category=category, filename=filename, lineno=lineno,
            format="%(filename)s:%(lineno)s: %(category)s: %(warning)s")
    else:
        _oldshowwarning(message, category, filename, lineno, filename)

_keepErrors = 0
_keptErrors = []
_ignoreErrors = []

def startKeepingErrors():
    """Support function for testing frameworks.

    Start keeping errors in a buffer which can be retrieved (and emptied) with
    flushErrors.
    """
    global _keepErrors
    _keepErrors = 1


def flushErrors(*errorTypes):
    """Support function for testing frameworks.

    Return a list of errors that occurred since the last call to flushErrors().
    (This will return None unless startKeepingErrors has been called.)
    """

    global _keptErrors
    k = _keptErrors
    _keptErrors = []
    if errorTypes:
        for erk in k:
            shouldReLog = 1
            for errT in errorTypes:
                if erk.check(errT):
                    shouldReLog = 0
            if shouldReLog:
                err(erk)
    return k

def ignoreErrors(*types):
    for type in types:
        _ignoreErrors.append(type)

def clearIgnores():
    global _ignoreErrors
    _ignoreErrors = []

def err(_stuff=None,**kw):
    """Write a failure to the log.
    """
    if _stuff is None:
        _stuff = failure.Failure()
    if isinstance(_stuff, failure.Failure):
        if _keepErrors:
            if _ignoreErrors:
                keep = 0
                for err in _ignoreErrors:
                    r = _stuff.check(err)
                    if r:
                        keep = 0
                        break
                    else:
                        keep = 1
                if keep:
                    _keptErrors.append(_stuff)
            else:
                _keptErrors.append(_stuff)
        msg(failure=_stuff, isError=1, **kw)
    elif isinstance(_stuff, Exception):
        msg(failure=failure.Failure(_stuff), isError=1, **kw)
    else:
        msg(repr(_stuff), isError=1, **kw)

deferr = err

class Logger:
    """
    This represents a class which may 'own' a log. Used by subclassing.
    """
    def logPrefix(self):
        """
        Override this method to insert custom logging behavior.  Its
        return value will be inserted in front of every line.  It may
        be called more times than the number of output lines.
        """
        return '-'


class EscapeFromTheMeaninglessConfinesOfCapital:
    def own(self, owner):
        warnings.warn("Foolish capitalist!  Your opulent toilet will be your undoing!!",
                      DeprecationWarning, stacklevel=2)
    def disown(self, owner):
        warnings.warn("The proletariat is victorious.",
                      DeprecationWarning, stacklevel=2)

logOwner = EscapeFromTheMeaninglessConfinesOfCapital()


class LogPublisher:
    """Class for singleton log message publishing."""
    
    synchronized = ['msg']

    def __init__(self):
        self.observers = []

    def addObserver(self, other):
        """Add a new observer.

        Observers are callable objects that will be called with each new log
        message (a dict).
        """
        self.observers.append(other)

    def removeObserver(self, other):
        """Remove an observer."""
        self.observers.remove(other)

    def msg(self, *message, **kw):
        """Log a new message."""
        actualEventDict = (context.get(ILogContext) or {}).copy()
        actualEventDict.update(kw)
        actualEventDict['message'] = message
        actualEventDict['time'] = time.time()
        for o in self.observers:
            o(actualEventDict)


try:
    theLogPublisher
except NameError:
    theLogPublisher = LogPublisher()
    addObserver = theLogPublisher.addObserver
    removeObserver = theLogPublisher.removeObserver
    msg = theLogPublisher.msg


def initThreads():
    global msg
    # after the log publisher is synchronized, grab its method again so we get
    # the hooked version
    msg = theLogPublisher.msg

threadable.synchronize(LogPublisher)
threadable.whenThreaded(initThreads)


class FileLogObserver:
    """Log observer that writes to a file-like object."""
    
    def __init__(self, f):
        self.write = f.write
        self.flush = f.flush

    def _emit(self, eventDict):
        edm = eventDict['message']
        if not edm:
            if eventDict['isError'] and eventDict.has_key('failure'):
                text = eventDict['failure'].getTraceback()
            elif eventDict.has_key('format'):
                text = eventDict['format'] % eventDict
        else:
            text = ' '.join(map(str, edm))
        y,mon,d,h,min, iigg,nnoo,rree,daylight = time.localtime(eventDict['time'])
        self.write("%0.4d/%0.2d/%0.2d %0.2d:%0.2d %s [%s] %s\n" %
                   (y, mon, d, h, min, time.tzname[daylight],
                    eventDict['system'], text.replace("\n","\n\t")))
        self.flush()                    # hoorj!

    def start(self):
        """Start observing log events."""
        addObserver(self._emit)

    def stop(self):
        """Stop observing log events."""
        removeObserver(self._emit)


class StdioOnnaStick:
    """Class that pretends to be stout/err."""
    
    closed = 0
    softspace = 0
    mode = 'wb'
    name = '<stdio (log)>'

    def __init__(self, isError=0):
        self.isError = isError
        self.buf = ''

    def close(self):
        pass

    def fileno(self):
        return -1

    def flush(self):
        pass

    def read(self):
        raise IOError("can't read from the log!")

    readline = read
    readlines = read
    seek = read
    tell = read

    def write(self, data):
        d = (self.buf + data).split('\n')
        self.buf = d[-1]
        messages = d[0:-1]
        for message in messages:
            msg(message, printed=1, isError=self.isError)

    def writelines(self, lines):
        for line in lines:
            msg(line, printed=1, isError=self.isError)


try:
    _oldshowwarning
except NameError:
    _oldshowwarning = None


def startLogging(file, setStdout=1):
    """Initialize logging to a specified file."""
    global defaultObserver, _oldshowwarning
    if not _oldshowwarning:
        _oldshowwarning = warnings.showwarning
        warnings.showwarning = showwarning
    if defaultObserver:
        defaultObserver.stop()
        defaultObserver = None
    flo = FileLogObserver(file)
    flo.start()
    msg("Log opened.")
    if setStdout:
        sys.stdout = logfile
        sys.stderr = logerr


class NullFile:
    softspace = 0
    def read(self): pass
    def write(self, bytes): pass
    def flush(self): pass
    def close(self): pass


def discardLogs():
    """Throw away all logs.
    """
    global logfile
    logfile = NullFile()


# Prevent logfile from being erased on reload.  This only works in cpython.
try:
    logfile
except NameError:
    logfile = StdioOnnaStick(0)
    logerr = StdioOnnaStick(1)


class DefaultObserver:
    """Default observer.

    Will ignore all non-error messages and send error messages to sys.stderr.
    Will be removed when startLogging() is called for the first time.
    """

    def _emit(self, eventDict):
        if eventDict["isError"]:
            if eventDict.has_key('failure'):
                text = eventDict['failure'].getTraceback()
            else:
                text = " ".join([str(m) for m in eventDict["message"]]) + "\n"
            sys.stderr.write(text)
            sys.stderr.flush()
    
    def start(self):
        addObserver(self._emit)

    def stop(self):
        removeObserver(self._emit)


try:
    defaultObserver
except NameError:
    defaultObserver = DefaultObserver()
    defaultObserver.start()
