
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


"""
twisted.delay: Support for delayed and execution of events.

DEPRECATED.
"""

import warnings
warnings.warn("twisted.python.delay is deprecated. Please use reactor methods.",
              DeprecationWarning, stacklevel=2)


# System Imports
import os

if os.name != 'java':
    import errno

from time import sleep, time
from bisect import insort

# Sibling Imports
import rebuild
import log

TICKS = 0
FUNC  = 1
ARGS  = 2

class StopLooping(Exception):
    """Stop a loop.
    When this exception is raised within a looping call, it will stop the loop,
    but be caught silently.
    """
    def __init__(self):
        """Automatically raise me on initialization."""
        Exception.__init__(self)
        raise self

class Looping:
    """Base class for looping callbacks.
    """
    stopped = 0

    def __init__(self, ticks,func,delayed):
        """Looping(ticks,func,delayed)

        This initializer is only called internally.
        """
        self.ticks = ticks

        self.func = func
        self.delayed = delayed

    def rebuildUpdate(self, updater):
        self.func = updater(self.func)

    def stop(self):
        """Externally stop a looped event from recurring.
        """
        self.stopped = 1

    def loop(self, *args,**kw):
        """call my function with the given arguments, then reschedule me
        """
        if self.stopped:
            self.__stopped()
        try:
            apply(self.func,args,kw)
        except StopLooping:
            self.__stopped()
        except:
            self.__stopped()
            raise
        else:
            self.delayed._later(self.loop,self.ticks,args)

    def __stopped(self):
        """(internal) I've been stopped; break potential circular references."""
        del self.func
        del self.delayed

class Steps(Looping):
    """A class to represent a series of steps.
    """
    offset=0
    def __init__(self, ticks,func,list,delayed):
        """Initialize.
        """
        Looping.__init__(self,ticks,self.step,delayed)
        self.list=list
        self.func2=func

    def rebuildUpdate(self, updater):
        Looping.rebuildUpdate(self, updater)
        self.func2 = updater(self.func2)

    def step(self):
        """Execute one step through.
        """
        self.func2(self.list[self.offset])
        self.offset=self.offset+1
        if self.offset >= len(self.list):
            StopLooping()

class Later:
    """I am a function which will run later.
    """
    running = 1

    def __init__(self, func):
        """Create me with a function.
        """
        self.func = func

    def run(self, *args, **kw):
        """If I'm still running, apply the arguments to my function.
        """
        if self.running:
            try:
                apply(self.func, args, kw)
            finally:
                self.stop()

    def stop(self):
        """Cause me not to execute any longer when run() is called.
        """
        if self.running:
            self.running = 0
            del self.func

    def rebuildUpdate(self, updater):
        self.func = updater(self.func)


class IDelayed:
    """Interface implemented by Delayed objects - delayed event queues."""

    def timeout(self):
        """Return maximum number of seconds between calls of runUntilCurrent.

        The returned value should either be a float, or None if we don't want
        to affect the event loop.
        """

    def runUntilCurrent(self):
        """This will be called on every iteration of the event loop.

        This is where the delayed work should be done.
        """



class Time:
    """I am a list of events which will happen at particular points in time.
    """
    __implements__ = IDelayed

    def __init__(self):
        self.queue = []

    def __repr__(self):
        return '<twisted Time %s>' % (self.queue,)

    def runLater(self, seconds, func, *args, **kw):
        """Run an event a specified number of seconds later.
        """
        insort(self.queue, [time() + seconds, func, args, kw])

    def __getstate__(self):
        """Save state by storing all callback timeouts as differences from the current time.
        """
        now = time()
        newQueue = []
        for seconds, func, args, kw in self.queue:
            newQueue.append([seconds - now, func, args, kw])
        return {'queue': newQueue}

    def timeout(self):
        """IDelayed.timeout
        """
        if self.queue:
            return max(self.queue[0][0] - time(), 0) # time of first element in queue
        else:
            return None

    def runUntilCurrent(self):
        """IDelayed.runUntilCurrent
        """
        now = time()
        while self.queue and (self.queue[0][0] < now):
            seconds, func, args, kw = self.queue.pop(0)
            try:
                apply(func, args, kw)
            except:
                log.deferr()

    def runEverything(self):
        for seconds, func, args, kw in self.queue[:]:
            try:
                apply(func, args, kw)
            except:
                log.deferr()





class LockstepSimulation(rebuild.Sensitive):
    """I am a delayed event queue.

    A delayed event scheduler which, in my humble but correct opinion, is much
    better and more featureful than the built-in 'sched' module, especially
    when you're working with event insertions from multiple threads.

    Various methods in this class return Stoppable objects; each of these has a
    single stop() method which will cause the method that created them to be
    cancelled.  In the case of a loop, the loop will be stopped; a series of
    steps will be stopped in the middle, and a single method call will not be
    made.
    """

    __implements__ = IDelayed

    fudgefactor = 0.01

    def __init__(self):
        """ Initialize the delayed event queue. """
        self.queue = []
        self.ticks = 0
        self.is_running = 1
        self.ticktime = 5
        self.last_tick = time() # when was the last tick processed

    def __setstate__(self, dict):
        """Delayed.__setstate__(dict) -> None

        Flags this Delayed as current, so that unpickled Delayeds
        won't attempt to run hundreds of updates so they'll be
        current.
        """
        self.__dict__ = dict
        self.last_tick = time()
        self.rebuildUpToDate()


    def _later(self, func,ticks=0,args=()):
        """(internal) used by later, step, loop; inserts something into the queue"""
        insort(self.queue, (self.ticks-ticks,func,args))


    def later(self, func, ticks=0, args=()):
        """Delayed.later(func [, ticks [, args]]) -> Stoppable

        This function schedules the function 'func' for execution with
        the arguments 'args', 'ticks' ticks in the future.  A 'tick'
        is one call to the 'run' function.
        """
        later = Later(func)
        self._later(later.run, ticks, args)
        return later


    def step(self, func,list,ticks=0):
        """Delayed.step(func,list[,ticks]) -> Stoppable

        This schedules the function *func* for execution with each
        element in *list* as its only argument, pausing *ticks* ticks
        between each invocation.
        """
        steps = Steps(ticks,func,list,self)
        self._later(steps.loop)
        return steps

    def loop(self, func,ticks=0,args=()):
        """Delayed.loop(func[, ticks=0][, args=()]) -> Stoppable

        This schedules the function *func* for repeating execution
        every *ticks* ticks.
        """
        looping = Looping(ticks, func, self)
        self._later(looping.loop, args=args, ticks=ticks)
        return looping

    def timeout(self):
        """Delayed.timeout() -> integer (representing seconds)

        This says approximately how long from the current time this
        delay expects to get another run() call.
        """
        now = time()
        then = self.last_tick
        interval = self.ticktime
        timeout = (interval - (now - then))
        if timeout < 0.:
            return 0.
        else:
            return timeout

    def runUntilCurrent(self):
        """Delayed.runUntilCurrent() -> None

        This will run this delayed object until it is up-to-date with
        delay expects to get another run() callthe current clock time.
        """
        now = time()
        then = self.last_tick
        passed = now - then
        interval = self.ticktime
        intervalPlus = self.ticktime + self.fudgefactor
        while passed > intervalPlus:
            passed = passed - interval
            self.run()

    def run(self):
        """Delayed.run() -> None

        This runs one cycle of events, and moves the tickcount by one.
        (I would say "increments", but it actually decrements it for
        simplicity of implementation reasons. -glyph)
        """
        if self.needRebuildUpdate():
            log.msg( "Rebuilding Delayed Event Queue..." )
            for ticks, func, args in self.queue:
                # it's going to be an instance of one of the above, so just
                # pull on its instance.
                func.im_self.rebuildUpdate(self.latestVersionOf)
            self.rebuildUpToDate()
            log.msg( "Rebuilt." )

        self.last_tick = time()
        sticks = self.ticks - 1
        self.ticks = sticks
        while self.queue and self.queue[-1][TICKS] > sticks:
            pop = self.queue.pop()
            try:
                apply(pop[FUNC], pop[ARGS])
            except:
                log.deferr()

    def runEverything(self):
        """Run all currently-pending callbacks.
        """
        q = self.queue[:]
        self.queue = []
        for ticks, func, args in q:
            try:
                apply(func,args)
            except:
                log.deferr()

    def runloop(self):
        """Runs until the is_running flag is false.
        """
        try:
            while self.is_running:
                self.run()
                sleep(self.ticktime)
        except IOError, x:
            # the 'errno' module won't be available in jython, but that should be OK.
            if x.errno == errno.EINTR:
                log.msg( "(delay loop interrupted)" )
            else:
                raise

    def threadloop(self):
        """Run self.runloop in a separate thread.
        """
        self.is_running = 1
        import threading
        t = threading.Thread(target=self.runloop)
        t.start()

    def stop(self):
        """In multithreaded mode, stops threads started by self.threadloop()
        """
        self.is_running=0

Delayed = LockstepSimulation
