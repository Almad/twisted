# -*- test-case-name: twisted.test.test_defer -*-
#
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

"""Support for results that aren't immediately available.

API Stability: stable

Maintainer: U{Glyph Lefkowitz<mailto:glyph@twistedmatrix.com>}
"""

from __future__ import nested_scopes

# Twisted imports
from twisted.python import log, failure


class AlreadyCalledError(Exception):
    pass

class AlreadyArmedError(Exception):
    pass

class TimeoutError(Exception):
    pass

def logError(err):
    log.err(err)
    return err

def succeed(result):
    d = Deferred()
    d.callback(result)
    return d

class _nothing: pass

def fail(result=_nothing):
    if result is _nothing:
        result = failure.Failure()
    d = Deferred()
    d.errback(result)
    return d

def execute(callable, *args, **kw):
    """Create a deferred from a callable and arguments.

    Call the given function with the given arguments.  Return a deferred which
    has been fired with its callback as the result of that invocation or its
    errback with a Failure for the exception thrown.
    """
    try:
        result = callable(*args, **kw)
    except:
        return fail()
    else:
        return succeed(result)

def maybeDeferred(f, *args, **kw):
    """Invoke a function that may or may not return a deferred.
    
    Call the given function with the given arguments.  If the returned
    object is a C{Deferred}, return it.  If the returned object is a C{Failure},
    wrap it with C{fail} and return it.  Otherwise, wrap it in C{succeed} and
    return it.  If an exception is raised, convert it to a C{Failure}, wrap it
    in C{fail}, and then return it.

    @type f: Any callable
    @param f: The callable to invoke
    
    @param args: The arguments to pass to C{f}
    @param kw: The keyword arguments to pass to C{f}
    
    @rtype: C{Deferred}
    @return: The result of the function call, wrapped in a C{Deferred} if
    necessary.

    API Stability: Unstable
    """
    deferred = None
    if isinstance(f, Deferred) or f is None:
        import warnings
        warnings.warn("First argument to maybeDeferred() should no longer be a Deferred or None.  Just pass the function and the arguments.", DeprecationWarning)
        deferred = f or Deferred()
        f = args[0]
        args = args[1:]

    try:
        result = f(*args, **kw)
    except:
        if deferred is None:
            return fail(failure.Failure())
        else:
            deferred.errback(failure.Failure())
    else:
        if isinstance(result, Deferred):
            if deferred is None:
                return result
            else:
                result.chainDeferred(deferred)
        elif isinstance(result, failure.Failure):
            if deferred is None:
                return fail(result)
            else:
                deferred.errback(result)
        else:
            if deferred is None:
                return succeed(result)
            else:
                deferred.callback(result)
    return deferred

def timeout(deferred):
    deferred.errback(failure.Failure(TimeoutError("Callback timed out")))

def passthru(arg):
    return arg

class Deferred:
    """This is a callback which will be put off until later.

    Why do we want this? Well, in cases where a function in a threaded
    program would block until it gets a result, for Twisted it should
    not block. Instead, it should return a Deferred.

    This can be implemented for protocols that run over the network by
    writing an asynchronous protocol for twisted.internet. For methods
    that come from outside packages that are not under our control, we use
    threads (see for example L{twisted.enterprise.adbapi}).

    For more information about Deferreds, see doc/howto/defer.html or
    U{http://www.twistedmatrix.com/documents/howto/defer}
    """

    called = 0
    default = 0
    paused = 0
    timeoutCall = None

    def __init__(self):
        self.callbacks = []

    def addCallbacks(self, callback, errback=None,
                     callbackArgs=None, callbackKeywords=None,
                     errbackArgs=None, errbackKeywords=None, asDefaults=0):
        """Add a pair of callbacks (success and error) to this Deferred.

        These will be executed when the 'master' callback is run.
        """
        cbs = ((callback, callbackArgs, callbackKeywords),
               (errback or (passthru), errbackArgs, errbackKeywords))
        if self.default:
            self.callbacks[-1] = cbs
        else:
            self.callbacks.append(cbs)
        self.default = asDefaults
        if self.called:
            self._runCallbacks()
        return self

    def addCallback(self, callback, *args, **kw):
        """Convenience method for adding just a callback.

        See L{addCallbacks}.
        """
        return self.addCallbacks(callback, callbackArgs=args,
                                 callbackKeywords=kw)

    def addErrback(self, errback, *args, **kw):
        """Convenience method for adding just an errback.

        See L{addCallbacks}.
        """
        return self.addCallbacks(passthru, errback,
                                 errbackArgs=args,
                                 errbackKeywords=kw)

    def addBoth(self, callback, *args, **kw):
        """Convenience method for adding a single callable as both a callback
        and an errback.

        See L{addCallbacks}.
        """
        return self.addCallbacks(callback, callback,
                                 callbackArgs=args, errbackArgs=args,
                                 callbackKeywords=kw, errbackKeywords=kw)

    def chainDeferred(self, d):
        """Chain another Deferred to this Deferred.

        This method adds callbacks to this Deferred to call d's callback or
        errback, as appropriate."""
        return self.addCallbacks(d.callback, d.errback)

    def callback(self, result):
        """Run all success callbacks that have been added to this Deferred.

        Each callback will have its result passed as the first
        argument to the next; this way, the callbacks act as a
        'processing chain'. Also, if the success-callback returns a Failure
        or raises an Exception, processing will continue on the *error*-
        callback chain.
        """
        self._startRunCallbacks(result)


    def errback(self, fail=None):
        """Run all error callbacks that have been added to this Deferred.

        Each callback will have its result passed as the first
        argument to the next; this way, the callbacks act as a
        'processing chain'. Also, if the error-callback returns a non-Failure
        or doesn't raise an Exception, processing will continue on the
        *success*-callback chain.

        If the argument that's passed to me is not a failure.Failure instance,
        it will be embedded in one. If no argument is passed, a failure.Failure
        instance will be created based on the current traceback stack.

        Passing a string as `fail' is deprecated, and will be punished with
        a warning message.
        """
        if not isinstance(fail, failure.Failure):
            fail = failure.Failure(fail)

        self._startRunCallbacks(fail)


    def pause(self):
        """Stop processing on a Deferred until L{unpause}() is called.
        """
        self.paused = self.paused + 1


    def unpause(self):
        """Process all callbacks made since L{pause}() was called.
        """
        self.paused = self.paused - 1
        if self.paused:
            return
        if self.called:
            self._runCallbacks()

    def _continue(self, result):
        self.result = result
        self.unpause()

    def _startRunCallbacks(self, result):
        if self.called:
            raise AlreadyCalledError()
        self.called = True
        self.result = result
        if self.timeoutCall:
            try:
                self.timeoutCall.cancel()
            except:
                pass
            # Avoid reference cycles, because this object defines __del__
            del self.timeoutCall
        self._runCallbacks()


    def _runCallbacks(self):
        if not self.paused:
            cb = self.callbacks
            self.callbacks = []
            while cb:
                item = cb.pop(0)
                callback, args, kw = item[
                    isinstance(self.result, failure.Failure)]
                args = args or ()
                kw = kw or {}
                try:
                    self.result = callback(self.result, *args, **kw)
                    if isinstance(self.result, Deferred):
                        self.callbacks = cb

                        # note: this will cause _runCallbacks to be called
                        # "recursively" sometimes... this shouldn't cause any
                        # problems, since all the state has been set back to
                        # the way it's supposed to be, but it is useful to know
                        # in case something goes wrong.  deferreds really ought
                        # not to return themselves from their callbacks.
                        self.pause()
                        self.result.addBoth(self._continue)
                        break
                except:
                    self.result = failure.Failure()
        if isinstance(self.result, failure.Failure):
            self.result.cleanFailure()


    def arm(self):
        """This method is deprecated.
        """
        pass

    def setTimeout(self, seconds, timeoutFunc=timeout, *args, **kw):
        """Set a timeout function to be triggered if I am not called.

        @param seconds: How long to wait (from now) before firing the
        timeoutFunc.

        @param timeoutFunc: will receive the Deferred and *args, **kw as its
        arguments.  The default timeoutFunc will call the errback with a
        L{TimeoutError}.
        """

        assert not self.timeoutCall, "Don't call setTimeout twice on the same Deferred."

        from twisted.internet import reactor
        self.timeoutCall = reactor.callLater(
            seconds,
            lambda: self.called or timeoutFunc(self, *args, **kw))
        return self.timeoutCall

    armAndErrback = errback
    armAndCallback = callback
    armAndChain = chainDeferred


    def __str__(self):
        if hasattr(self, 'result'):
            return "<Deferred at %s  current result: %r>" % (hex(id(self)),
                                                            self.result)
        return "<Deferred at %s>" % hex(id(self))
    __repr__ = __str__


    def __del__(self):
        """Print tracebacks and die.

        If the *last* (and I do mean *last*) callback leaves me in an error
        state, print a traceback (if said errback is a Failure).
        """
        if (self.called and
            isinstance(self.result, failure.Failure)):
            log.msg("Unhandled error in Deferred:")
            log.err(self.result)


class DeferredList(Deferred):
    """I combine a group of deferreds into one callback.

    I track a list of L{Deferred}s for their callbacks, and make a single
    callback when they have all completed, a list of (success, result)
    tuples, 'success' being a boolean.

    Note that you can still use a L{Deferred} after putting it in a
    DeferredList.  In particular, if you want to suppress 'Unhandled error in
    Deferred' messages, you will still need to add errbacks to the Deferreds
    *after* putting them in the DeferredList, as a DeferredList won't swallow
    the errors.
    """

    fireOnOneCallback = 0
    fireOnOneErrback = 0

    def __init__(self, deferredList, fireOnOneCallback=0, fireOnOneErrback=0):
        """Initialize a DeferredList.

        @type deferredList:  C{list} of L{Deferred}s
        @param deferredList: The list of deferreds to track.
        @param fireOnOneCallback: (keyword param) a flag indicating that
                             only one callback needs to
                             be fired for me to call my callback
        @param fireOnOneErrback: (keyword param) a flag indicating that
                            only one errback needs to be fired for me to
                            call my errback
        """
        self.resultList = [None] * len(deferredList)
        Deferred.__init__(self)
        if len(deferredList) == 0:
            self.callback([])

        index = 0
        for deferred in deferredList:
            deferred.addCallbacks(self._cbDeferred, self._cbDeferred,
                                  callbackArgs=(index,SUCCESS),
                                  errbackArgs=(index,FAILURE))
            index = index + 1

        self.fireOnOneCallback = fireOnOneCallback
        self.fireOnOneErrback = fireOnOneErrback

    def addDeferred(self, deferred):
        self.resultList.append(None)
        index = len(self.resultList) - 1
        deferred.addCallbacks(self._cbDeferred, self._cbDeferred,
                                  callbackArgs=(index,SUCCESS),
                                  errbackArgs=(index,FAILURE))

    def _cbDeferred(self, result, index, succeeded):
        """(internal) Callback for when one of my deferreds fires.
        """
        self.resultList[index] = (succeeded, result)

        if not self.called:
            if succeeded == SUCCESS and self.fireOnOneCallback:
                self.callback((result, index))
            elif succeeded == FAILURE and self.fireOnOneErrback:
                self.errback(failure.Failure((result, index)))
            elif None not in self.resultList:
                self.callback(self.resultList)
        return result


def _parseDListResult(l, fireOnOneErrback=0):
    if __debug__:
        for success, value in l:
            assert success
    return [x[1] for x in l]

def gatherResults(deferredList, fireOnOneErrback=0):
    """Returns list with result of given Deferreds.

    This builds on C{DeferredList} but is useful since you don't
    need to parse the result for success/failure.

    @type deferredList:  C{list} of L{Deferred}s
    """
    if fireOnOneErrback:
        raise "This function was previously totally, totally broken.  Please fix your code to behave as documented."
    d = DeferredList(deferredList, fireOnOneErrback=1)
    d.addCallback(_parseDListResult)
    return d

# Constants for use with DeferredList

SUCCESS = 1
FAILURE = 0

__all__ = ["Deferred", "DeferredList", "succeed", "fail", "FAILURE", "SUCCESS",
           "AlreadyCalledError", "TimeoutError", "gatherResults",
          ]
