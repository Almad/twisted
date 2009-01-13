# Copyright (c) 2009 Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for L{twisted.test.proto_helpers.StringTransport}.
"""

from zope.interface.verify import verifyObject

from twisted.internet.interfaces import ITransport, IPushProducer, IConsumer
from twisted.trial.unittest import TestCase
from twisted.test.proto_helpers import StringTransport


class StringTransportTests(TestCase):
    """
    Tests for L{twisted.test.proto_helpers.StringTransport}.
    """
    def setUp(self):
        self.transport = StringTransport()


    def test_interfaces(self):
        """
        L{StringTransport} instances provide L{ITransport}, L{IPushProducer},
        and L{IConsumer}.
        """
        self.assertTrue(verifyObject(ITransport, self.transport))
        self.assertTrue(verifyObject(IPushProducer, self.transport))
        self.assertTrue(verifyObject(IConsumer, self.transport))


    def test_registerProducer(self):
        """
        L{StringTransport.registerProducer} records the arguments supplied to
        it as instance attributes.
        """
        producer = object()
        streaming = object()
        self.transport.registerProducer(producer, streaming)
        self.assertIdentical(self.transport.producer, producer)
        self.assertIdentical(self.transport.streaming, streaming)


    def test_disallowedRegisterProducer(self):
        """
        L{StringTransport.registerProducer} raises L{RuntimeError} if a
        producer is already registered.
        """
        producer = object()
        self.transport.registerProducer(producer, True)
        self.assertRaises(
            RuntimeError, self.transport.registerProducer, object(), False)
        self.assertIdentical(self.transport.producer, producer)
        self.assertTrue(self.transport.streaming)


    def test_unregisterProducer(self):
        """
        L{StringTransport.unregisterProducer} causes the transport to forget
        about the registered producer and makes it possible to register a new
        one.
        """
        oldProducer = object()
        newProducer = object()
        self.transport.registerProducer(oldProducer, False)
        self.transport.unregisterProducer()
        self.assertIdentical(self.transport.producer, None)
        self.transport.registerProducer(newProducer, True)
        self.assertIdentical(self.transport.producer, newProducer)
        self.assertTrue(self.transport.streaming)


    def test_invalidUnregisterProducer(self):
        """
        L{StringTransport.unregisterProducer} raises L{RuntimeError} if called
        when no producer is registered.
        """
        self.assertRaises(RuntimeError, self.transport.unregisterProducer)


    def test_initialProducerState(self):
        """
        L{StringTransport.producerState} is initially C{'producing'}.
        """
        self.assertEqual(self.transport.producerState, 'producing')


    def test_pauseProducing(self):
        """
        L{StringTransport.pauseProducing} changes the C{producerState} of the
        transport to C{'paused'}.
        """
        self.transport.pauseProducing()
        self.assertEqual(self.transport.producerState, 'paused')


    def test_resumeProducing(self):
        """
        L{StringTransport.resumeProducing} changes the C{producerState} of the
        transport to C{'producing'}.
        """
        self.transport.pauseProducing()
        self.transport.resumeProducing()
        self.assertEqual(self.transport.producerState, 'producing')


    def test_stopProducing(self):
        """
        L{StringTransport.stopProducing} changes the C{'producerState'} of the
        transport to C{'stopped'}.
        """
        self.transport.stopProducing()
        self.assertEqual(self.transport.producerState, 'stopped')


    def test_stoppedTransportCannotPause(self):
        """
        L{StringTransport.pauseProducing} raises L{RuntimeError} if the
        transport has been stopped.
        """
        self.transport.stopProducing()
        self.assertRaises(RuntimeError, self.transport.pauseProducing)


    def test_stoppedTransportCannotResume(self):
        """
        L{StringTransport.resumeProducing} raises L{RuntimeError} if the
        transport has been stopped.
        """
        self.transport.stopProducing()
        self.assertRaises(RuntimeError, self.transport.resumeProducing)


    def test_disconnectingTransportCannotPause(self):
        """
        L{StringTransport.pauseProducing} raises L{RuntimeError} if the
        transport is being disconnected.
        """
        self.transport.loseConnection()
        self.assertRaises(RuntimeError, self.transport.pauseProducing)


    def test_disconnectingTransportCannotResume(self):
        """
        L{StringTransport.resumeProducing} raises L{RuntimeError} if the
        transport is being disconnected.
        """
        self.transport.loseConnection()
        self.assertRaises(RuntimeError, self.transport.resumeProducing)
