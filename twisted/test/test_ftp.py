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
from __future__ import  nested_scopes

from twisted.trial import unittest
from twisted.protocols import ftp, loopback
from twisted.internet import reactor
from twisted.internet.protocol import Protocol, FileWrapper, Factory, \
                                      ClientFactory

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import sys, types, os.path

from twisted.test.test_protocols import StringIOWithoutClosing

from twisted.python import log


class UtilTestCase(unittest.TestCase):
    def testDecodeHostPort(self):
        data = "999 The magic address is (123,234,56,78,11,22)"
        host, port = ftp.decodeHostPort(data)
        self.failUnlessEqual(host, '123.234.56.78')
        self.failUnlessEqual(port, (11*256) + 22)


class BufferingProtocol(Protocol):
    def __init__(self):
        self.buf = StringIO()
    def dataReceived(self, data):
        self.buf.write(data)


class FTPClientTests(unittest.TestCase):
    def testFailedRETR(self):
        try:
            f = Factory()
            f.noisy = 0
            f.protocol = Protocol
            port = reactor.listenTCP(0, f, interface="127.0.0.1")
            n = port.getHost()[2]
            # This test data derived from a bug report by ranty on #twisted
            responses = ['220 ready, dude (vsFTPd 1.0.0: beat me, break me)',
                         # USER anonymous
                         '331 Please specify the password.',
                         # PASS twisted@twistedmatrix.com
                         '230 Login successful. Have fun.',
                         # TYPE I
                         '200 Binary it is, then.',
                         # PASV
                         '227 Entering Passive Mode (127,0,0,1,%d,%d)' %
                         (n>>8, n&0xff),
                         # RETR /file/that/doesnt/exist
                         '550 Failed to open file.']

            b = StringIOWithoutClosing()
            client = ftp.FTPClient(passive=1)
            client.makeConnection(FileWrapper(b))
            self.writeResponses(client, responses)
            p = Protocol()
            d = client.retrieveFile('/file/that/doesnt/exist', p)
            d.addCallback(lambda r, self=self:
                            self.fail('Callback incorrectly called: %r' % r))
            d.addBoth(lambda ignored,r=reactor: r.crash())

            id = reactor.callLater(2, self.timeout)
            reactor.run()
            log.flushErrors(ftp.FTPError)
            try:
                id.cancel()
            except:
                pass
        finally:
            try:
                port.stopListening()
                reactor.iterate()
            except:
                pass

    def timeout(self):
        reactor.crash()
        self.fail('Timed out')

    def writeResponses(self, protocol, responses):
        for response in responses:
            reactor.callLater(0.1, protocol.lineReceived, response)


class FTPServerTests(unittest.TestCase):
    def setUp(self):
        """Creates an FTP server

        The FTP will serve files from the directory this module resides in.
        """
        self.serverFactory = ftp.FTPFactory()
        self.serverFactory.noisy = 0
        serverPath = os.path.abspath('.') #
        self.serverFactory.root = serverPath

        self.serverPort = reactor.listenTCP(0, self.serverFactory, interface='127.0.0.1')
        self.ftp_port = self.serverPort.getHost()[2]
        open('ftp_crap', 'w').write('HELLO hello HELLO\n\n\n')
        try:
            os.remove('HelloThere')
        except Exception, e:
            pass
        

    def tearDown(self):
        self.serverPort.stopListening()
        # Make sure the port really is closed, to avoid "address already in use"
        # errors.
        try:
            del self.result
        except:
            pass
        try:
            del self.error
        except:
            pass

        reactor.iterate()


class FTPClientAndServerTests(FTPServerTests):
    """These test the FTP Client against the FTP Server"""
    passive = 0

    def errback(self, failure):
        try:
            self.fail('Errback called: ' + str(failure))
        except Exception, e:
            self.error = sys.exc_info()
            raise

    def callback(self, result):
        self.result = result

    def testLongFileListings(self):
        # Connect
        client = ftp.FTPClient(passive=self.passive)
        factory = ClientFactory()
        factory.noisy = 0
        factory.buildProtocol = lambda s, c=client: c
        reactor.connectTCP('localhost', self.ftp_port, factory)

        # Issue the command and set the callbacks
        fileList = ftp.FTPFileListProtocol()
        d = client.list('.', fileList)
        d.addCallbacks(self.callback, self.errback)

        # Wait for the result
        id = reactor.callLater(5, self.errback, "timed out") # timeout so we don't freeze
        while not hasattr(self, 'result') and not hasattr(self, 'error'):
            reactor.iterate()
        try:
            id.cancel()
        except ValueError: pass

        error = getattr(self, 'error', None)
        if error:
            raise error[0], error[1], error[2]

        # Check that the listing contains this file (ftp_crap)
        filenames = map(lambda file: file['filename'], fileList.files)
        self.failUnless('ftp_crap' in filenames,
                        'ftp_crap not in file listing')

    def testShortFileListings(self):

        # Connect
        client = ftp.FTPClient(passive=self.passive)
        factory = ClientFactory()
        factory.noisy = 0
        factory.buildProtocol = lambda s, c=client: c
        reactor.connectTCP('localhost', self.ftp_port, factory)

        # Issue the command and set the callbacks
        p = BufferingProtocol()
        d = client.nlst('.', p)
        d.addCallbacks(self.callback, self.errback)

        # Wait for the result
        id = reactor.callLater(5, self.errback, "timed out") # timeout so we don't freeze
        while not hasattr(self, 'result') and not hasattr(self, 'error'):
            reactor.iterate()
        try:
            id.cancel()
        except ValueError: pass

        error = getattr(self, 'error', None)
        if error:
            raise error[0], error[1], error[2]

        # Check that the listing contains this file (ftp_crap)
        filenames = p.buf.getvalue().split('\r\n')
        self.failUnless('ftp_crap' in filenames,
                        'ftp_crap not in file listing')

    def testRetr(self):
        # Connect
        client = ftp.FTPClient(passive=self.passive)
        factory = ClientFactory()
        factory.noisy = 0
        factory.buildProtocol = lambda s, c=client: c
        reactor.connectTCP('localhost', self.ftp_port, factory)

        # download ftp_crap
        

        proto = BufferingProtocol()
        d = client.retr(os.path.basename('ftp_crap'), proto)
        d.addCallbacks(self.callback, self.errback)

        # Wait for a result
        id = reactor.callLater(5, self.errback, "timed out") # timeout so we don't freeze
        while not hasattr(self, 'result') and not hasattr(self, 'error'):
            reactor.iterate()
        try:
            id.cancel()
        except ValueError: pass

        error = getattr(self, 'error', None)
        if error:
            raise error[0], error[1], error[2]

        # Check that the file is the same as read directly off the disk
        self.failUnless(type(self.result) == types.ListType,
                        'callback result is wrong type: ' + str(self.result))
        data = proto.buf.getvalue()
        self.failUnless(data == open('ftp_crap', "rb").read(),
                        'RETRieved file does not match original')


    def testStor(self):
        # Connect
        client = ftp.FTPClient(passive=self.passive)
        client.debug = 1
        factory = ClientFactory()
        factory.noisy = 0
        factory.buildProtocol = lambda s, c=client: c
        reactor.connectTCP('localhost', self.ftp_port, factory)

        expectedContent = "Hello\n"*4
        
        def gotResult(c):
            c.write(expectedContent)
            c.finish()

        def gotErr(f):
            self.errback(f)

        t = client.storeFile("HelloThere")
        t[0].addCallbacks(gotResult, gotErr)
        t[1].addCallbacks(self.callback, self.errback)

        # Wait for a result
        id = reactor.callLater(5, self.errback, "timed out") # timeout so we don't freeze
        while not hasattr(self, 'result') and not hasattr(self, 'error'):
            reactor.iterate()
        try:
            id.cancel()
        except ValueError: pass

        error = getattr(self, 'error', None)
        if error:
            raise error[0], error[1], error[2]

        self.assertEquals(open('HelloThere').read(), expectedContent)

    testStor.todo = 'The server is broken'

    def testBadLogin(self):
        client = ftp.FTPClient(passive=self.passive, username='badperson')

        # Deferreds catch Exceptions raised in callbacks, which interferes with
        # unittest.TestCases, so we jump through a few hoops to make sure the
        # failure is triggered correctly.
        self.callbackException = None
        def badResult(result, self=self):
            try:
                self.fail('Got this file listing when login should have failed: ' +
                          str(result))
            except Exception, e:
                self.callbackException = sys.exc_info()
                raise

        errors = [None, None]
        def gotError(failure, x, errors_=errors):
            errors_[x] = failure

        # These LIST commands should should both fail
        d = client.list('.', ftp.FTPFileListProtocol())
        d.addCallbacks(badResult, gotError, errbackArgs=(0,))
        d = client.list('.', ftp.FTPFileListProtocol())
        d.addCallbacks(badResult, gotError, errbackArgs=(1,))

        factory = ClientFactory()
        factory.noisy = 0
        factory.buildProtocol = lambda s,c=client: c
        reactor.connectTCP('localhost', self.ftp_port, factory)
        while None in errors and not self.callbackException:
            reactor.iterate()

        if self.callbackException:
            ce = self.callbackException
            raise ce[0], ce[1], ce[2]

        log.flushErrors(ftp.ConnectionLost)


class FTPPassiveClientAndServerTests(FTPClientAndServerTests):
    """Identical to FTPClientTests, except with passive transfers.

    That's right ladies and gentlemen!  I double the number of tests with a
    trivial subclass!  Hahaha!
    """
    passive = 1

    def testStor(self):
        FTPClientAndServerTests.testStor(self)


class FTPFileListingTests(unittest.TestCase):
    def testOneLine(self):
        # This example line taken from the docstring for FTPFileListProtocol
        fileList = ftp.FTPFileListProtocol()
        class PrintLine(Protocol):
            def connectionMade(self):
                self.transport.write('-rw-r--r--   1 root     other        531 Jan 29 03:26 README\n')
                self.transport.loseConnection()
        loopback.loopback(PrintLine(), fileList)
        file = fileList.files[0]
        self.failUnless(file['filetype'] == '-', 'misparsed fileitem')
        self.failUnless(file['perms'] == 'rw-r--r--', 'misparsed perms')
        self.failUnless(file['owner'] == 'root', 'misparsed fileitem')
        self.failUnless(file['group'] == 'other', 'misparsed fileitem')
        self.failUnless(file['size'] == 531, 'misparsed fileitem')
        self.failUnless(file['date'] == 'Jan 29 03:26', 'misparsed fileitem')
        self.failUnless(file['filename'] == 'README', 'misparsed fileitem')


if __name__ == '__main__':
    unittest.main()
