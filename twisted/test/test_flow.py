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
#
# Author: Clark C. Evans
#
from twisted.flow import flow
from twisted.trial import unittest
from twisted.python import failure
from twisted.internet import defer, reactor, protocol

class slowlist:
    """ this is a generator based list

        def slowlist(list):
            list = list[:]
            while list:
               yield list.pop(0)

        It is primarly used to simulate generators by using
        a list (for testing purposes) without being wrapped
        as a flow.List, which has all kinds of shortcuts we
        don't want for testing.
    """
    def __init__(self, list):
        self.list = list[:]
    def __iter__(self):
        return self
    def next(self):
        if self.list:
            return self.list.pop(0)
        raise StopIteration

_onetwothree = ['one','two',flow.Cooperate(),'three']

class producer:
    """ iterator version of the following generator... 

        def producer():
            lst = flow.wrap(slowlist([1,2,3]))
            nam = flow.wrap(slowlist(_onetwothree))
            while True: 
                yield lst
                yield nam
                yield (lst.next(),nam.next())

    """
    def __iter__(self):
        self.lst   = flow.wrap(slowlist([1,2,3]))
        self.nam   = flow.wrap(slowlist(_onetwothree))
        self.next = self.yield_lst
        return self
    def yield_lst(self):
        self.next = self.yield_nam
        return self.lst
    def yield_nam(self):
        self.next = self.yield_results
        return self.nam
    def yield_results(self):
        self.next = self.yield_lst
        return (self.lst.next(), self.nam.next())

class consumer:
    """ iterator version of the following generator...

        def consumer():
            title = flow.wrap(['Title'])
            prod = flow.wrap(producer())
            yield title
            yield title.next()
            yield prod
            for data in prod:
                yield data
                yield prod
    """    
    def __iter__(self):
        self.title = flow.wrap(['Title'])
        self.lst   = flow.wrap(producer())
        self.next = self.yield_title
        return self
    def yield_title(self):
        self.next = self.yield_title_result
        return self.title
    def yield_title_result(self):
        self.next = self.yield_lst
        return self.title.next()
    def yield_lst(self):
        self.next = self.yield_result
        return self.lst
    def yield_result(self):
        self.next = self.yield_lst
        return self.lst.next()


class badgen:
    """ a bad generator...

    def badgen():
        yield 'x'
        err =  3/ 0
    """    
    def __iter__(self):
        self.next = self.yield_x
        return self
    def yield_x(self):
        self.next = self.yield_done
        return 'x'
    def yield_done(self):
        err = 3 / 0
        raise StopIteration

class buildlist:
    """ building a list

        def buildlist(src):
            out = []
            yield src
            for itm in src:
                out.append(itm)
                yield src
            yield out
    """
    def __init__(self, src):
        self.src  = src
    def __iter__(self):
        self.out  = []
        self.next = self.yield_src
        return self
    def yield_src(self):
        self.next = self.yield_append
        return self.src
    def yield_append(self):
        try:
            self.out.append(self.src.next())
        except StopIteration: 
            self.next = self.yield_finish
            return self.out
        return self.src
    def yield_finish(self):
        raise StopIteration

class testconcur:
    """ interweving two concurrent stages

        def testconcur(*stages):
            both = flow.Concurrent(*stages)
            yield both
            for stage in both:
                yield (stage.name, stage.result)
                yield both
    """
    def __init__(self, *stages):
        self.both = flow.Concurrent(*stages)
    def __iter__(self):
        self.next = self.yield_both
        return self
    def yield_both(self): 
        self.next = self.yield_result
        return self.both
    def yield_result(self):
        self.next = self.yield_both
        stage = self.both.next()
        return (stage.name, stage.next())

class echoServer:
    """ a simple echo protocol, server side

        def echoServer(conn):
            yield conn
            for data in conn:
                yield data
                yield conn
    """
    def __init__(self, conn):
        self.conn = conn
    def __iter__(self):
        self.next = self.yield_conn
        return self
    def yield_conn(self):
        self.next = self.yield_data
        return self.conn
    def yield_data(self):
        self.next = self.yield_conn
        return self.conn.next()

class echoClient:
    """ a simple echo client tester

        def echoClient(conn):
            yield "testing"
            yield conn
            # signal that we are done
            conn.d.callback(conn.next())
    """
    def __init__(self, conn):
        self.conn = conn
    def __iter__(self):
        self.next = self.yield_testing
        return self
    def yield_testing(self):
        self.next = self.yield_conn
        return "testing"
    def yield_conn(self):
        self.next = self.yield_stop
        return self.conn
    def yield_stop(self):
        # signal that we are done
        self.conn.factory.d.callback(self.conn.next())
        raise StopIteration()
 
class FlowTest(unittest.TestCase):
    def testNotReady(self):
        x = flow.wrap([1,2,3])
        self.assertRaises(flow.NotReadyError,x.next)

    def testBasic(self):
        lhs = ['string']
        rhs = list(flow.Block('string'))
        self.assertEqual(lhs,rhs)

    def testBasicList(self):
        lhs = [1,2,3]
        rhs = list(flow.Block([1,2,flow.Cooperate(),3]))
        self.assertEqual(lhs,rhs)

    def testBasicIterator(self):
        lhs = ['one','two','three']
        rhs = list(flow.Block(slowlist(_onetwothree)))
        self.assertEqual(lhs,rhs)

    def testCallable(self):
        lhs = ['one','two','three']
        rhs = list(flow.Block(slowlist(_onetwothree)))
        self.assertEqual(lhs,rhs)

    def testProducer(self):
        lhs = [(1,'one'),(2,'two'),(3,'three')]
        rhs = list(flow.Block(producer()))
        self.assertEqual(lhs,rhs)

    def testConsumer(self):
        lhs = ['Title',(1,'one'),(2,'two'),(3,'three')]
        rhs = list(flow.Block(consumer))
        self.assertEqual(lhs,rhs)

    def testFailure(self):
        self.assertRaises(ZeroDivisionError, list, flow.Block(badgen()))
        self.assertEqual(['x',ZeroDivisionError],
                         list(flow.Block(badgen(),ZeroDivisionError)))
        self.assertEqual(['x',ZeroDivisionError],
                         list(flow.Block(flow.wrap(badgen()),
                                                   ZeroDivisionError)))

    def testZip(self):
        lhs = [(1,'a'),(2,'b'),(3,None)]
        mrg = flow.Zip([1,2,flow.Cooperate(),3],['a','b'])
        rhs = list(flow.Block(mrg))
        self.assertEqual(lhs,rhs)

    def testMerge(self):
        lhs = ['one', 1, 'two', 2, 3, 'three']
        mrg = flow.Merge(slowlist(_onetwothree),slowlist([1,2,3]))
        rhs = list(flow.Block(mrg))
        self.assertEqual(lhs,rhs)

    def testFilter(self):
        def odd(val):
            if val % 2:
                return True
        lhs = [ 1, 3 ]
        mrg = flow.Filter(odd,slowlist([1,2,flow.Cooperate(),3]))
        rhs = list(flow.Block(mrg))
        self.assertEqual(lhs,rhs)

    def testDeferred(self):
        lhs = ['Title', (1,'one'),(2,'two'),(3,'three')]
        d = flow.Deferred(consumer())
        self.assertEquals(lhs, unittest.deferredResult(d))

    def testBuildList(self):
        src = flow.wrap([1,2,3])
        out = flow.Block(buildlist(src)).next()
        self.assertEquals(out,[1,2,3])

    def testDeferredFailure(self):
        d = flow.Deferred(badgen())
        unittest.deferredError(d).trap(ZeroDivisionError)

    def testDeferredTrap(self):
        d = flow.Deferred(badgen(), ZeroDivisionError)
        r = unittest.deferredResult(d)
        self.assertEqual(r, ['x',ZeroDivisionError])

    def testZipFailure(self):
        lhs = [(1,'a'),(2,'b'),(3,'c')]
        mrg = flow.Zip([1,2,flow.Cooperate(),3],badgen())
        d = flow.Deferred(mrg)
        unittest.deferredError(d).trap(ZeroDivisionError)

    def testDeferredWrapper(self):
        from twisted.internet import defer
        from twisted.internet import reactor 
        a = defer.Deferred()
        reactor.callLater(0, lambda: a.callback("test"))
        b = flow.Merge(a, slowlist([1,2,flow.Cooperate(),3]))
        rhs = unittest.deferredResult(flow.Deferred(b))
        self.assertEquals(rhs, [1, 2, 'test', 3])
    
    def testDeferredWrapperFail(self):
        from twisted.internet import defer
        from twisted.internet import reactor 
        d = defer.Deferred()
        f = lambda: d.errback(flow.Failure(IOError()))
        reactor.callLater(0, f)
        unittest.deferredError(d).trap(IOError)

    def testCallback(self):
        cb = flow.Callback()
        d = flow.Deferred(buildlist(cb))
        for x in range(9):
            cb.result(x)
        cb.finish()
        rhs = unittest.deferredResult(d)
        self.assertEquals([range(9)],rhs)

    def testCallbackFailure(self):
        cb = flow.Callback()
        d = flow.Deferred(buildlist(cb))
        for x in range(3):
            cb.result(x)
        cb.errback(flow.Failure(IOError()))
        unittest.deferredError(d).trap(IOError)

    def testConcurrentCallback(self):
        ca = flow.Callback()
        ca.name = 'a'
        cb = flow.Callback()
        cb.name = 'b'
        d = flow.Deferred(testconcur(ca,cb))
        ca.result(1)
        cb.result(2)
        ca.result(3)
        ca.result(4)
        ca.finish()
        cb.result(5)
        cb.finish()
        rhs = unittest.deferredResult(d)
        self.assertEquals([('a',1),('b',2),('a',3),('a',4),('b',5)],rhs)

    def testProtocolLocalhost(self):
        PORT = 8392
        server = protocol.ServerFactory()
        server.protocol = flow.Protocol
        server.protocol.controller = echoServer
        reactor.listenTCP(PORT,server)
        client = protocol.ClientFactory()
        client.protocol = flow.makeProtocol(echoClient)
        client.d = defer.Deferred()
        reactor.connectTCP("localhost", PORT, client)
        self.assertEquals('testing', unittest.deferredResult(client.d))

    def testProtocol(self):
        from twisted.protocols import loopback
        server = flow.Protocol()
        server.controller = echoServer
        client = flow.makeProtocol(echoClient)()
        client.factory = protocol.ClientFactory()
        client.factory.d = defer.Deferred()
        loopback.loopback(server, client)
        self.assertEquals('testing', unittest.deferredResult(client.factory.d))

    def _disabled_testThreaded(self):
        from time import sleep
        #self.fail("This test freezes and consumes 100% CPU.")
        class CountIterator:
            def __init__(self, count):
                self.count = count
            def __iter__(self):
                return self
            def next(self): # this is run in a separate thread
                sleep(.1)
                val = self.count
                if not(val):
                    raise StopIteration
                self.count -= 1
                return val
        result = [7,6,5,4,3,2,1]
        d = flow.Deferred(flow.Threaded(CountIterator(7)))
        self.assertEquals(result, unittest.deferredResult(d))
        d = flow.Deferred(flow.Threaded(CountIterator(7)))
        sleep(2)
        self.assertEquals(result, unittest.deferredResult(d))
        d = flow.Deferred(flow.Threaded(CountIterator(7)))
        sleep(.3)
        self.assertEquals(result, unittest.deferredResult(d))

