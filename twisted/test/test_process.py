
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
Test running processes.
"""

from pyunit import unittest

import cStringIO, gzip, os, popen2, time, sys

# Twisted Imports
from twisted.internet import reactor
from twisted.protocols import protocol
from twisted.python import util, runtime

s = "there's no place like home!\n" * 3


class TestProcessProtocol(protocol.ProcessProtocol):

    finished = 0
    
    def connectionMade(self):
        self.stages = [1]
        self.data = ''
        self.err = ''
        self.transport.write("abcd")

    def dataReceived(self, data):
        self.data = self.data + data

    def connectionLost(self):
        self.stages.append(2)
        if self.data != "abcd":
            raise RuntimeError
        self.transport.write("abcd")

    def errReceived(self, data):
        self.err = self.err + data

    def errConnectionLost(self):
        self.stages.append(3)
        if self.err != "1234":
            raise RuntimeError
        self.transport.write("abcd")
        self.stages.append(4)

    def processEnded(self):
        self.finished = 1
        
    
class ProcessTestCase(unittest.TestCase):
    """Test running a process."""
    
    def testProcess(self):
        exe = sys.executable
        scriptPath = util.sibpath(__file__, "process_tester.py")
        p = TestProcessProtocol()
        reactor.spawnProcess(p, exe, ["python", "-u", scriptPath])
        while not p.finished:
            reactor.iterate()
        self.assertEquals(p.stages, [1, 2, 3, 4])


##class PosixProcessTestCase(unittest.TestCase):
##    """Test running processes."""
    
##    def testProcess(self):
##        f = cStringIO.StringIO()
##        if os.path.exists('/bin/gzip'): cmd = '/bin/gzip'
##        elif os.path.exists('/usr/bin/gzip'): cmd = '/usr/bin/gzip'
##        else: raise "gzip not found in /bin or /usr/bin"
##        p = process.Process(cmd, [cmd, "-"], {}, "/tmp")
##        p.handleChunk = f.write
##        p.write(s)
##        p.closeStdin()
##        while hasattr(p, 'writer'):
##            main.iterate()
##        f.seek(0, 0)
##        gf = gzip.GzipFile(fileobj=f)
##        self.assertEquals(gf.read(), s)
    
##    def testStderr(self):
##        # we assume there is no file named ZZXXX..., both in . and in /tmp
##        if not os.path.exists('/bin/ls'): raise "/bin/ls not found"
##        err = popen2.popen3("/bin/ls ZZXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")[2].read()
##        f = cStringIO.StringIO()
##        p = process.Process('/bin/ls', ["/bin/ls", "ZZXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"], {}, "/tmp")
##        p.handleError = f.write
##        p.closeStdin()
##        while hasattr(p, 'writer'):
##            main.iterate()
##        self.assertEquals(err, f.getvalue())
    
##    # XXX
##    # Python popen has issues on Unix, this is probably not really a Twisted bug
##    # XXX
##    #
##    #def testPopen(self):
##    #    """Make sure popen isn't broken by our signal handlers."""
##    #    main.handleSignals() # install signal handlers
##    #    for i in range(20):
##    #        f = os.popen("/bin/gzip --help")
##    #        f.read()
##    #        f.close()


##class Win32ProcessTestCase(unittest.TestCase):
##    """Test process programs that are packaged with twisted."""
    
##    def testStdinReader(self):
##        import win32api
##        pyExe = win32api.GetModuleFileName(0)
##        errF = cStringIO.StringIO()
##        outF = cStringIO.StringIO()
##        scriptPath = util.sibpath(__file__, "process_stdinreader.py")
##        p = process.Process(pyExe, [pyExe, "-u", scriptPath], None, None)
##        p.handleError = errF.write
##        p.handleChunk = outF.write
##        main.iterate()
        
##        p.write("hello, world")
##        p.closeStdin()
##        while not p.closed:
##            main.iterate()
##        self.assertEquals(errF.getvalue(), "err\nerr\n")
##        self.assertEquals(outF.getvalue(), "out\nhello, world\nout\n")


##if runtime.platform.getType() != 'posix':
##    del PosixProcessTestCase
##elif runtime.platform.getType() != 'win32':
##    del Win32ProcessTestCase

