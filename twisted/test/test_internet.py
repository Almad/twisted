# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.


from twisted.trial import unittest
from twisted.trial.util import spinUntil
from twisted.internet import reactor, protocol, error, app, abstract
from twisted.internet import interfaces
from twisted.internet.utils import getProcessOutput

try:
    from twisted.internet import ssl
except ImportError:
    ssl = None
if ssl and not ssl.supported:
    ssl = None

from twisted.internet.defer import SUCCESS, FAILURE, Deferred, succeed, fail
from twisted.python import util, log

import os
import sys
import time
import types

class SystemEventTestCase(unittest.TestCase):
    def setUp(self):
        self.triggers = []
    def addTrigger(self, event, phase, func):
        t = reactor.addSystemEventTrigger(event, phase, func)
        self.triggers.append(t)
        return t
    def removeTrigger(self, trigger):
        reactor.removeSystemEventTrigger(trigger)
        self.triggers.remove(trigger)
    def tearDown(self):
        for t in self.triggers:
            try:
                reactor.removeSystemEventTrigger(t)
            except:
                pass

    def testTriggerSystemEvent1(self):
        l = []
        l2 = []
        d = Deferred()
        d2 = Deferred()
        def _returnDeferred(d=d):
            return d
        def _returnDeferred2(d2=d2):
            return d2
        def _appendToList(l=l):
            l.append(1)
        def _appendToList2(l2=l2):
            l2.append(1)
        ##         d.addCallback(lambda x: sys.stdout.write("firing d\n"))
        ##         d2.addCallback(lambda x: sys.stdout.write("firing d2\n"))
        r = reactor

        self.addTrigger("before", "test", _appendToList)
        self.addTrigger("during", "test", _appendToList)
        self.addTrigger("after", "test", _appendToList)
        self.assertEquals(len(l), 0, "Nothing happened yet.")
        r.fireSystemEvent("test")
        r.iterate()
        self.assertEquals(len(l), 3, "Should have filled the list.")

        l[:]=[]
        self.addTrigger("before", "defer", _returnDeferred)
        self.addTrigger("before", "defer", _returnDeferred2)
        self.addTrigger("during", "defer", _appendToList)
        self.addTrigger("after", "defer", _appendToList)
        r.fireSystemEvent("defer")
        self.assertEquals(len(l), 0, "Event should not have fired yet.")
        d.callback(None)
        self.assertEquals(len(l), 0, "Event still should not have fired yet.")
        d2.callback(None)
        self.assertEquals(len(l), 2)

        l[:]=[]
        a = self.addTrigger("before", "remove", _appendToList)
        b = self.addTrigger("before", "remove", _appendToList2)
        self.removeTrigger(b)
        r.fireSystemEvent("remove")
        self.assertEquals(len(l), 1)
        self.assertEquals(len(l2), 0)

    def testTriggerSystemEvent2(self):
        # one of the "before" trigger functions returns a deferred. A later
        # "before" trigger fires the deferred. A third before runs. Then a
        # "during" should be run. One of the failure modes for the old
        # cReactor code is to start the "during" as soon as the deferred
        # fires, rather than waiting for the "before" phase to be finished
        l = []
        d = Deferred()
        d2 = Deferred()
        def _returnDeferred(d=d):
            return d
        def _fireDeferred(d=d):
            d.callback(None)
        def _returnDeferred2(d2=d2):
            return d2
        def _appendToList(l=l):
            l.append(1)
        r = reactor
        # to test this properly, the triggers must fire in this sequence:
        # _returnDeferred, _fireDeferred, _returnDeferred2 . cReactor happens
        # to run triggers in the order in which they were added.
        self.addTrigger("before", "defer2", _returnDeferred)
        self.addTrigger("before", "defer2", _fireDeferred)
        self.addTrigger("before", "defer2", _returnDeferred2)
        self.addTrigger("during", "defer2", _appendToList)
        self.addTrigger("after", "defer2", _appendToList)
        r.fireSystemEvent("defer2")
        self.assertEquals(len(l), 0, "Event should not have fired yet.")
        d2.callback(None)
        self.assertEquals(len(l), 2)

    def testTriggerSystemEvent3(self):
        # make sure reactor can survive the loss of an event type while
        # waiting for a before-trigger's Deferred to fire
        l = []
        d = Deferred()
        d2 = Deferred()
        def _returnDeferred(d=d):
            return d
        def _appendToList(l=l):
            l.append(1)
        def _ignore(failure):
            return None
        r = reactor
        b1 = self.addTrigger("before", "defer3", _returnDeferred)
        b2 = self.addTrigger("after", "defer3", _appendToList)
        r.fireSystemEvent("defer3")
        self.assertEquals(len(l), 0, "Event should not have fired yet.")
        self.removeTrigger(b1)
        self.removeTrigger(b2)
        try:
            d.callback(None) # cReactor gives errback to deferred
        except ValueError:
            pass
        self.assertEquals(len(l), 0)
        d.addErrback(_ignore)

    def testTriggerSystemEvent4(self):
        # make sure interleaved event types do not interfere with each other.
        # Old cReactor code had a single defer_list for all event types.
        l = []
        l2 = []
        d = Deferred()
        d2 = Deferred()
        def _returnDeferred(d=d):
            return d
        def _returnDeferred2(d2=d2):
            return d2
        def _appendToList(l=l):
            l.append(1)
        def _appendToList2(l2=l2):
            l2.append(1)
        r = reactor
        self.addTrigger("before", "event1", _returnDeferred)
        self.addTrigger("after", "event1", _appendToList)
        self.addTrigger("before", "event2", _returnDeferred2)
        self.addTrigger("after", "event2", _appendToList2)
        r.fireSystemEvent("event1")
        # event1 should be waiting on deferred 'd'
        r.fireSystemEvent("event2")
        # event2 should be waiting on deferred 'd2'
        self.assertEquals(len(l), 0, "Event should not have fired yet.")
        self.assertEquals(len(l2), 0, "Event should not have fired yet.")
        d.callback(None)
        # event1 should run "during" and "after" stages
        # event2 should still be waiting on d2
        self.assertEquals(len(l), 1)
        self.assertEquals(len(l2), 0)
        d2.callback(None)
        # event2 should run "during" and "after" stages
        self.assertEquals(len(l), 1)
        self.assertEquals(len(l2), 1)

    def testTriggerSystemEvent5(self):
        # make sure the reactor can handle attempts to remove bogus triggers
        l = []
        def _appendToList(l=l):
            l.append(1)
        r = reactor
        b = self.addTrigger("after", "event1", _appendToList)
        self.removeTrigger(b)
        if type(b) == types.IntType:
            bogus = b + 40
            self.failUnlessRaises(ValueError,
                                  r.removeSystemEventTrigger, bogus)
        self.failUnlessRaises(TypeError,
                              r.removeSystemEventTrigger, None)


class InterfaceTestCase(unittest.TestCase):

    _called = 0

    def _callback(self, x, **d):
        """Callback for testCallLater"""
        self.assertEquals(x, 1)
        self.assertEquals(d, {'a': 1})
        self._called = 1
        self._calledTime = time.time()

    def testCallLater(self):
        # add and remove a callback
        def bad():
            raise RuntimeError, "this shouldn't have been called"
        i = reactor.callLater(0.1, bad)
        i.cancel()

        self.assertRaises(error.AlreadyCancelled, i.cancel)

        i = reactor.callLater(0.5, self._callback, 1, a=1)
        start = time.time()

        spinUntil(lambda :self._called, 5)

        self.assertApproximates(self._calledTime, start + 0.5, 0.2 )
        self.assertRaises(error.AlreadyCalled, i.cancel)

        del self._called
        del self._calledTime

    def _resetcallback(self):
        self._resetcallbackTime = time.time()

    def _delaycallback(self):
        self._delaycallbackTime = time.time()

    def testCallLaterDelayAndReset(self):
        # this test will fail if the test host is busy and this script is
        # delayed by more than about 100ms
        self._resetcallbackTime = None
        self._delaycallbackTime = None
        ireset = reactor.callLater(0.4, self._resetcallback)
        idelay = reactor.callLater(0.5, self._delaycallback)
        start = time.time()
        # chug a little before delaying
        while time.time() - start < 0.2:
            reactor.iterate(0.01)
        ireset.reset(0.4) # move expiration from 0.4 to (now)0.2+0.4=0.6
        idelay.delay(0.3) # move expiration from 0.5 to (orig)0.5+0.3=0.8
        # both should be called sometime during this
        while time.time() - start < 2:
            reactor.iterate(0.01)
        ireset_elapsed = self._resetcallbackTime - start
        idelay_elapsed = self._delaycallbackTime - start
        #self.assertApproximates(ireset_elapsed, 0.6, 0.4,
        #                        "ireset fired at %f (wanted 0.6)" % \
        #                        ireset_elapsed)
        #self.assertApproximates(idelay_elapsed, 0.8, 0.4,
        #                        "idelay fired at %f (wanted 0.8)" % \
        #                        idelay_elapsed)
        self.failUnless(idelay_elapsed >= ireset_elapsed,
                        "got %f, %f" % (idelay_elapsed, ireset_elapsed))
        self.failUnless(ireset_elapsed >= (0.6-0.05),
                        "got %f (wanted 0.6)" % ireset_elapsed)
        self.failUnless(idelay_elapsed >= (0.8-0.05),
                        "got %f (wanted 0.8)" % idelay_elapsed)

        del self._resetcallbackTime
        del self._delaycallbackTime

    def testCallLaterTime(self):
        d = reactor.callLater(10, lambda: None)
        try:
            self.failUnless(d.getTime() - (time.time() + 10) < 1)
        finally:
            d.cancel()
    
    def testCallInNextIteration(self):
        calls = []
        def f1():
            calls.append('f1')
            reactor.callLater(0.0, f2)
        def f2():
            calls.append('f2')
            reactor.callLater(0.0, f3)
        def f3():
            calls.append('f3')
        
        reactor.callLater(0, f1)
        self.assertEquals(calls, [])
        reactor.iterate()
        self.assertEquals(calls, ['f1'])
        reactor.iterate()
        self.assertEquals(calls, ['f1', 'f2'])
        reactor.iterate()
        self.assertEquals(calls, ['f1', 'f2', 'f3'])

    def testDelayedCallStringification(self):
        # Mostly just make sure str() isn't going to raise anything for
        # DelayedCalls within reason.
        dc = reactor.callLater(0, lambda x, y: None, 'x', y=10)
        str(dc)
        dc.reset(5)
        str(dc)
        dc.cancel()
        str(dc)

        dc = reactor.callLater(0, lambda: None, x=[({'hello': u'world'}, 10j), reactor], *range(10))
        str(dc)
        dc.cancel()
        str(dc)

        def calledBack(ignored):
            str(dc)
        d = Deferred().addCallback(calledBack)
        dc = reactor.callLater(0, d.callback, None)
        str(dc)
        return d

    def testWakeUp(self):
        # Make sure other threads can wake up the reactor
        d = Deferred()
        def wake():
            time.sleep(0.1)
            # callFromThread will call wakeUp for us
            reactor.callFromThread(d.callback, None)
        reactor.callInThread(wake)
        return d

    if interfaces.IReactorThreads(reactor, None) is None:
        testWakeUp.skip = "Nothing to wake up for without thread support"


class ReactorCoreTestCase(unittest.TestCase):
    def setUp(self):
        self.triggers = []
        self.timers = []
    def addTrigger(self, event, phase, func):
        t = reactor.addSystemEventTrigger(event, phase, func)
        self.triggers.append(t)
        return t
    def removeTrigger(self, trigger):
        reactor.removeSystemEventTrigger(trigger)
        self.triggers.remove(trigger)
    def addTimer(self, when, func):
        t = reactor.callLater(when, func)
        self.timers.append(t)
        return t
    def removeTimer(self, timer):
        try:
            timer.cancel()
        except error.AlreadyCalled:
            pass
        self.timers.remove(timer)

    def tearDown(self):
        for t in self.triggers:
            try:
                reactor.removeSystemEventTrigger(t)
            except:
                pass
    def crash(self):
        reactor.crash()
    def stop(self):
        reactor.stop()

    def testRun(self):
        """Test that reactor.crash terminates reactor.run"""
        reactor.callLater(0.1, self.crash)
        reactor.run() # returns once .crash is called
        reactor.callLater(0.1, self.crash)
        reactor.run() # returns once .crash is called

    def testIterate(self):
        """Test that reactor.iterate(0) doesn't block"""
        start = time.time()
        # twisted timers are distinct from the underlying event loop's
        # timers, so this fail-safe probably won't keep a failure from
        # hanging the test
        t = reactor.callLater(10, self.crash)
        reactor.iterate(0) # shouldn't block
        stop = time.time()
        elapsed = stop - start
        #print "elapsed", elapsed
        self.failUnless(elapsed < 8)
        t.cancel()

    def timeout(self):
        print "test timed out"
        self.problem = 1
        self.fail("test timed out")
    def count(self):
        self.counter += 1

# XXX calling reactor.stop() in test suite causes problems with other tests
#     def testStop(self):
#         """reactor.stop should fire shutdown triggers"""
#         # make sure shutdown triggers are run when the reactor is stopped
#         self.counter = 0
#         self.problem = 0
#         self.addTrigger("before", "shutdown", self.count)
#         self.addTimer(0.1, self.stop)
#         t = self.addTimer(5, self.timeout)
#         reactor.run()
#         self.failUnless(self.counter == 1,
#                         "reactor.stop didn't invoke shutdown triggers")
#         self.failIf(self.problem, "the test timed out")
#         self.removeTimer(t)

    def testCrash(self):
        """reactor.crash should NOT fire shutdown triggers"""
        self.counter = 0
        self.problem = 0
        self.addTrigger("before", "shutdown", self.count)
        # reactor.crash called from an "after-startup" trigger is too early
        # for the gtkreactor: gtk_mainloop is not yet running. Same is true
        # when called with reactor.callLater(0). Must be >0 seconds in the
        # future to let gtk_mainloop start first.
        self.addTimer(0.1, self.crash)
        t = self.addTimer(5, self.timeout)
        reactor.run()
        # this will fire reactor.crash, which ought to exit .run without
        # running the event triggers
        self.failUnless(self.counter == 0,
                        "reactor.crash invoked shutdown triggers, "
                        "but it isn't supposed to")
        self.failIf(self.problem, "the test timed out")
        self.removeTimer(t)


class DelayedTestCase(unittest.TestCase):
    def setUp(self):
        self.finished = 0
        self.counter = 0
        self.timers = {}
        # ick. Sometimes there are magic timers already running:
        # popsicle.Freezer.tick . Kill off all such timers now so they won't
        # interfere with the test. Of course, this kind of requires that
        # getDelayedCalls already works, so certain failure modes won't be
        # noticed.
        if not hasattr(reactor, "getDelayedCalls"):
            return
        for t in reactor.getDelayedCalls():
            t.cancel()
        reactor.iterate() # flush timers

    def tearDown(self):
        for t in self.timers.values():
            t.cancel()

    def checkTimers(self):
        l1 = self.timers.values()
        l2 = list(reactor.getDelayedCalls())

        # There should be at least the calls we put in.  There may be other
        # calls that are none of our business and that we should ignore,
        # though.

        missing = []
        for dc in l1:
            if dc not in l2:
                missing.append(dc)
        if missing:
            self.finished = 1
        self.failIf(missing, "Should have been missing no calls, instead was missing " + repr(missing))

    def callback(self, tag):
        del self.timers[tag]
        self.checkTimers()

    def addCallback(self, tag):
        self.callback(tag)
        self.addTimer(15, self.callback)

    def done(self, tag):
        self.finished = 1
        self.callback(tag)

    def addTimer(self, when, callback):
        self.timers[self.counter] = reactor.callLater(when * 0.01, callback,
                                                      self.counter)
        self.counter += 1
        self.checkTimers()

    def testGetDelayedCalls(self):
        if not hasattr(reactor, "getDelayedCalls"):
            return
        # This is not a race because we don't do anything which might call
        # the reactor until we have all the timers set up. If we did, this
        # test might fail on slow systems.
        self.checkTimers()
        self.addTimer(35, self.done)
        self.addTimer(20, self.callback)
        self.addTimer(30, self.callback)
        which = self.counter
        self.addTimer(29, self.callback)
        self.addTimer(25, self.addCallback)
        self.addTimer(26, self.callback)

        self.timers[which].cancel()
        del self.timers[which]
        self.checkTimers()

        spinUntil(lambda :self.finished, 5)
        self.checkTimers()

    def testActive(self):
        dcall = reactor.callLater(0, lambda: None)
        self.assertEquals(dcall.active(), 1)
        reactor.iterate()
        self.assertEquals(dcall.active(), 0)

resolve_helper = """
import %(reactor)s
%(reactor)s.install()
from twisted.internet import reactor

class Foo:
    def __init__(self):
        reactor.callLater(1, self.start)
        self.timer = reactor.callLater(3, self.failed)
    def start(self):
        reactor.resolve('localhost').addBoth(self.done)
    def done(self, res):
        print 'done', res
        reactor.stop()
    def failed(self):
        print 'failed'
        self.timer = None
        reactor.stop()
f = Foo()
reactor.run()
"""

class Resolve(unittest.TestCase):
    # this uses t.i.util.getProcessOutput, and maybe it wants to live in
    # test_iutils.py instead of here
    def testChildResolve(self):
        # I've seen problems with reactor.run under gtk2reactor. Spawn a
        # child which just does reactor.resolve after a second of delay, and
        # fail if it does not complete in a timely fashion.
        helper = os.path.abspath(self.mktemp())
        helperf = open(helper, 'wt')
        reactorname = reactor.__module__
        helperf.write(resolve_helper % {'reactor': reactorname})
        helperf.close()
        env = os.environ.copy()
        env['PYTHONPATH'] = os.pathsep.join(sys.path)
        d = getProcessOutput(sys.executable, (helper,), env, errortoo=1)
        d.addCallback(self._testChildResolve_1)
        return d
    testChildResolve.timeout = 10
    def _testChildResolve_1(self, res):
        if res.startswith("failed\n"):
            print "The child process timed out. Output is:"
            print res
            self.fail("The child process timed out.")
        self.failUnlessEqual(res, "done 127.0.0.1\n")
if not interfaces.IReactorProcess(reactor, None):
    Resolve.skip = "cannot run test: reactor doesn't support IReactorProcess"


class Counter:
    index = 0

    def add(self):
        self.index = self.index + 1


class Order:

    stage = 0

    def a(self):
        if self.stage != 0: raise RuntimeError
        self.stage = 1

    def b(self):
        if self.stage != 1: raise RuntimeError
        self.stage = 2

    def c(self):
        if self.stage != 2: raise RuntimeError
        self.stage = 3


class callFromThreadTestCase(unittest.TestCase):
    """Task scheduling from threads tests."""

    if interfaces.IReactorThreads(reactor, None) is None:
        skip = "Nothing to test without thread support"

    def schedule(self, *args, **kwargs):
        """Override in subclasses."""
        reactor.callFromThread(*args, **kwargs)

    def testScheduling(self):
        c = Counter()
        for i in range(100):
            self.schedule(c.add)
        for i in range(100):
            reactor.iterate()
        self.assertEquals(c.index, 100)

    def testCorrectOrder(self):
        o = Order()
        self.schedule(o.a)
        self.schedule(o.b)
        self.schedule(o.c)
        reactor.iterate()
        reactor.iterate()
        reactor.iterate()
        self.assertEquals(o.stage, 3)

    def testNotRunAtOnce(self):
        c = Counter()
        self.schedule(c.add)
        # scheduled tasks should not be run at once:
        self.assertEquals(c.index, 0)
        reactor.iterate()
        self.assertEquals(c.index, 1)


class MyProtocol(protocol.Protocol):
    """Sample protocol."""

class MyFactory(protocol.Factory):
    """Sample factory."""

    protocol = MyProtocol


class ProtocolTestCase(unittest.TestCase):

    def testFactory(self):
        factory = MyFactory()
        protocol = factory.buildProtocol(None)
        self.assertEquals(protocol.factory, factory)
        self.assert_( isinstance(protocol, factory.protocol) )


class DummyProducer:
    resumed = 0
    stopped = 0
    def resumeProducing(self):
         self.resumed += 1

    def stopProducing(self):
         self.stopped += 1

class TestProducer(unittest.TestCase):

    def testDoubleProducer(self):
        fd = abstract.FileDescriptor()
        fd.connected = 1
        dp = DummyProducer()
        fd.registerProducer(dp, 0)
        self.assertEquals(dp.resumed, 1)
        self.assertRaises(RuntimeError, fd.registerProducer, DummyProducer(), 0)

    def testUnconnectedFileDescriptor(self):
        fd = abstract.FileDescriptor()
        fd.disconnected = 1
        dp = DummyProducer()
        fd.registerProducer(dp, 0)
        self.assertEquals(dp.stopped, 1)

class PortStringification(unittest.TestCase):
    if interfaces.IReactorTCP(reactor, None) is not None:
        def testTCP(self):
            p = reactor.listenTCP(0, protocol.ServerFactory())
            portNo = p.getHost().port
            self.assertNotEqual(str(p).find(str(portNo)), -1,
                                "%d not found in %s" % (portNo, p))
            return p.stopListening()

    if interfaces.IReactorUDP(reactor, None) is not None:
        def testUDP(self):
            p = reactor.listenUDP(0, protocol.DatagramProtocol())
            portNo = p.getHost().port
            self.assertNotEqual(str(p).find(str(portNo)), -1,
                                "%d not found in %s" % (portNo, p))
            return p.stopListening()

    if interfaces.IReactorSSL(reactor, None) is not None and ssl:
        def testSSL(self, ssl=ssl):
            pem = util.sibpath(__file__, 'server.pem')
            p = reactor.listenSSL(0, protocol.ServerFactory(), ssl.DefaultOpenSSLContextFactory(pem, pem))
            portNo = p.getHost().port
            self.assertNotEqual(str(p).find(str(portNo)), -1,
                                "%d not found in %s" % (portNo, p))
            return p.stopListening()
