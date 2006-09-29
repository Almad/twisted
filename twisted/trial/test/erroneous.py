# -*- test-case-name: twisted.trial.test.test_tests -*-
from twisted.trial import unittest, util
from twisted.internet import reactor, protocol, defer


class FoolishError(Exception):
    pass


class TestFailureInSetUp(unittest.TestCase):
    def setUp(self):
        raise FoolishError, "I am a broken setUp method"

    def test_noop(self):
        pass


class TestFailureInTearDown(unittest.TestCase):
    def tearDown(self):
        raise FoolishError, "I am a broken tearDown method"

    def test_noop(self):
        pass


class TestFailureInSetUpClass(unittest.TestCase):
    def setUpClass(self):
        raise FoolishError, "I am a broken setUpClass method"

    def test_noop(self):
        pass


class TestFailureInTearDownClass(unittest.TestCase):
    def tearDownClass(self):
        raise FoolishError, "I am a broken setUp method"

    def test_noop(self):
        pass


class TestRegularFail(unittest.TestCase):
    def test_fail(self):
        self.fail("I fail")

    def test_subfail(self):
        self.subroutine()

    def subroutine(self):
        self.fail("I fail inside")

class TestFailureInDeferredChain(unittest.TestCase):
    def test_fail(self):
        d = defer.Deferred()
        d.addCallback(self._later)
        reactor.callLater(0, d.callback, None)
        return d
    def _later(self, res):
        self.fail("I fail later")


class TestSkipTestCase(unittest.TestCase):
    pass

TestSkipTestCase.skip = "skipping this test"


class TestSkipTestCase2(unittest.TestCase):
    
    def setUpClass(self):
        raise unittest.SkipTest, "thi stest is fukct"

    def test_thisTestWillBeSkipped(self):
        pass


class DelayedCall(unittest.TestCase):
    hiddenExceptionMsg = "something blew up"
    
    def go(self):
        raise RuntimeError(self.hiddenExceptionMsg)

    def testHiddenException(self):
        """
        What happens if an error is raised in a DelayedCall and an error is
        also raised in the test?

        L{test_reporter.TestErrorReporting.testHiddenException} checks that
        both errors get reported.

        Note that this behaviour is deprecated. A B{real} test would return a
        Deferred that got triggered by the callLater. This would guarantee the
        delayed call error gets reported.
        """
        reactor.callLater(0, self.go)
        reactor.iterate(0.01)
        self.fail("Deliberate failure to mask the hidden exception")
    testHiddenException.suppress = [util.suppress(
        message=r'reactor\.iterate cannot be used.*',
        category=DeprecationWarning)]


class ReactorCleanupTests(unittest.TestCase):
    def test_leftoverPendingCalls(self):
        def _():
            print 'foo!'
        reactor.callLater(10000.0, _)

class SocketOpenTest(unittest.TestCase):
    def test_socketsLeftOpen(self):
        f = protocol.Factory()
        f.protocol = protocol.Protocol
        reactor.listenTCP(0, f)

class TimingOutDeferred(unittest.TestCase):
    def test_alpha(self):
        pass

    def test_deferredThatNeverFires(self):
        self.methodCalled = True
        d = defer.Deferred()
        return d

    def test_omega(self):
        pass


def unexpectedException(self):
    """i will raise an unexpected exception...
    ... *CAUSE THAT'S THE KINDA GUY I AM*
    
    >>> 1/0
    """

