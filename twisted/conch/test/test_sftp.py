# -*- test-case-name: twisted.conch.test.test_sftp -*-
# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE file for details.

from twisted.trial import unittest, util
try:
    from twisted.conch import unix
except ImportError:
    unix = None
from twisted.conch import avatar
from twisted.conch.ssh import filetransfer
from twisted.protocols import loopback
from twisted.internet import defer, reactor
from twisted.python import components, log

import os, os.path

class FileTransferTestAvatar(avatar.ConchUser): 

    def _runAsUser(self, f, *args, **kw):
        try:
            f = iter(f)
        except TypeError:
            f = [(f, args, kw)]
        for i in f:
            func = i[0]
            args = len(i)>1 and i[1] or ()
            kw = len(i)>2 and i[2] or {}
            r = func(*args, **kw)
        return r

    def getHomeDir(self):
        return os.path.join(os.getcwd(), 'sftp_test')
if unix:
    class FileTransferForTestAvatar(unix.SFTPServerForUnixConchUser):

        def gotVersion(self, version, otherExt):
            return {'conchTest' : 'ext data'}

        def extendedRequest(self, extName, extData):
            if extName == 'testExtendedRequest':
                return 'bar'
            raise NotImplementedError

    components.registerAdapter(FileTransferForTestAvatar, FileTransferTestAvatar, filetransfer.ISFTPServer)

class TestOurServerOurClient(unittest.TestCase):

    def setUp(self):
        self.avatar = FileTransferTestAvatar()
        self.server = filetransfer.FileTransferServer(avatar=self.avatar)
        clientTransport = loopback.LoopbackRelay(self.server)

        self.client = filetransfer.FileTransferClient()
        self._serverVersion = None
        self._extData = None
        def _(serverVersion, extData):
            self._serverVersion = serverVersion
            self._extData = extData
        self.client.gotServerVersion = _
        serverTransport = loopback.LoopbackRelay(self.client) 
        self.client.makeConnection(clientTransport)
        self.server.makeConnection(serverTransport)

        self.clientTransport = clientTransport
        self.serverTransport = serverTransport

        self._emptyBuffers()

        os.mkdir('sftp_test')

        file('sftp_test/testfile1','w').write('a'*10+'b'*10)
        file('sftp_test/testRemoveFile', 'w').write('a')
        file('sftp_test/testRenameFile', 'w').write('a')

    def tearDown(self):
        for f in ['testfile1', 'testRemoveFile', 'testRenameFile', 
                  'testRenamedFile', 'testLink']:
            try:
                os.remove('sftp_test/' + f)
            except OSError:
                pass
        os.rmdir('sftp_test')
    
    def _emptyBuffers(self):
        while self.serverTransport.buffer or self.clientTransport.buffer:
            self.serverTransport.clearBuffer()
            self.clientTransport.clearBuffer()

    def _waitWithBuffer(self, d, timeout=10):
        reactor.callLater(0.1, self._emptyBuffers)
        return util.wait(d, timeout)

    def testServerVersion(self):
        self.failUnlessEqual(self._serverVersion, 3)
        self.failUnlessEqual(self._extData, {'conchTest' : 'ext data'})

    def testOpenFile(self):
        d = self.client.openFile("testfile1", filetransfer.FXF_READ | \
                filetransfer.FXF_WRITE, {})
        openFile = self._waitWithBuffer(d)
        self.failUnlessEqual(filetransfer.ISFTPFile(openFile), openFile)
        bytes = self._waitWithBuffer(openFile.readChunk(0, 30))
        self.failUnlessEqual(bytes, 'a'*10 + 'b'*10)
        self._waitWithBuffer(openFile.writeChunk(20, 'c'*10))
        bytes = self._waitWithBuffer(openFile.readChunk(0, 30))
        self.failUnlessEqual(bytes, 'a'*10 + 'b'*10 + 'c'*10)
        attrs = self._waitWithBuffer(openFile.getAttrs())
        self._waitWithBuffer(openFile.close())
        d = openFile.getAttrs()
        self.failUnlessRaises(filetransfer.SFTPError, self._waitWithBuffer, d)
        log.flushErrors()
        attrs2 = self._waitWithBuffer(self.client.getAttrs('testfile1'))
        self.failUnlessEqual(attrs, attrs2)
        # XXX test setAttrs

    def testRemoveFile(self):
        d = self.client.getAttrs("testRemoveFile")
        result = self._waitWithBuffer(d)
        d = self.client.removeFile("testRemoveFile")
        result = self._waitWithBuffer(d)
        d = self.client.removeFile("testRemoveFile")
        self.failUnlessRaises(filetransfer.SFTPError, self._waitWithBuffer, d)

    def testRenameFile(self):
        d = self.client.getAttrs("testRenameFile")
        attrs = self._waitWithBuffer(d)
        d = self.client.renameFile("testRenameFile", "testRenamedFile")
        result = self._waitWithBuffer(d)
        d = self.client.getAttrs("testRenamedFile")
        self.failUnlessEqual(self._waitWithBuffer(d), attrs)

    def testDirectory(self):
        d = self.client.getAttrs("testMakeDirectory")
        self.failUnlessRaises(filetransfer.SFTPError, self._waitWithBuffer, d)
        d = self.client.makeDirectory("testMakeDirectory", {})
        result = self._waitWithBuffer(d)
        d = self.client.getAttrs("testMakeDirectory")
        attrs = self._waitWithBuffer(d)
        # XXX not until version 4/5
        # self.failUnlessEqual(filetransfer.FILEXFER_TYPE_DIRECTORY&attrs['type'], 
        #                     filetransfer.FILEXFER_TYPE_DIRECTORY)

        d = self.client.removeDirectory("testMakeDirectory")
        result = self._waitWithBuffer(d)
        d = self.client.getAttrs("testMakeDirectory")
        self.failUnlessRaises(filetransfer.SFTPError, self._waitWithBuffer, d)

    def testOpenDirectory(self):
        d = self.client.openDirectory('')
        openDir = self._waitWithBuffer(d)
        files = []
        for f in openDir:
            if isinstance(f, defer.Deferred):
                try:
                    f = self._waitWithBuffer(f)
                except EOFError:
                    break
            files.append(f[0])
        files.sort()
        self.failUnlessEqual(files, ['testRemoveFile', 'testRenameFile', 
                'testfile1']) 
        d = openDir.close()
        result = self._waitWithBuffer(d)

    def testLink(self):
        d = self.client.getAttrs('testLink')
        self.failUnlessRaises(filetransfer.SFTPError, self._waitWithBuffer, d)
        self._waitWithBuffer(self.client.makeLink('testLink', 'testfile1'))
        attrs = self._waitWithBuffer(self.client.getAttrs('testLink',1))
        attrs2 = self._waitWithBuffer(self.client.getAttrs('testfile1'))
        self.failUnlessEqual(attrs, attrs2)
        link = self._waitWithBuffer(self.client.readLink('testLink'))
        self.failUnlessEqual(link, os.path.join(os.getcwd(), 'sftp_test', 'testfile1'))
        realPath = self._waitWithBuffer(self.client.realPath('testLink'))
        self.failUnlessEqual(realPath, os.path.join(os.getcwd(), 'sftp_test', 'testfile1'))

    def testExtendedRequest(self):
        d = self.client.extendedRequest('testExtendedRequest', 'foo')
        self.failUnlessEqual(self._waitWithBuffer(d), 'bar')
        d = self.client.extendedRequest('testBadRequest', '')
        self.failUnlessRaises(NotImplementedError, self._waitWithBuffer, d)

if not unix:
    TestOurServerOurClient.skip = "don't run on non-posix"

