# -*- test-case-name: twisted.test.test_ftp -*-

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

"""File Transfer Protocol support for Twisted Python.

Stability: semi-stable

Maintainer: U{Andrew Bennetts<mailto:spiv@twistedmatrix.com>}

Future Plans: The server will be re-written.  The goal for the server is that
it should be secure, high-performance, and overloaded with stupid features.
The client is probably fairly final, but should share more code with the
server, and some details could still change.

Server TODO:

 * Authorization
   User / Password is stored in a dict (factory.userdict) in plaintext
   Use cred
   Separate USER / PASS from mainloop

 * Ascii-download
   Currently binary only. Ignores TYPE

 * Missing commands
   HELP, REST, STAT, ...

 * Print out directory-specific messages
   As in READMEs etc

 * Testing
   Test at every ftp-program available and on any platform.
   Automated tests

 * Security
   PORT needs to reply correctly if it fails
   The paths are done by os.path; use the "undocumented" module posixpath

 * Etc
   Documentation, Logging, Procedural content, Localization, Telnet PI,
   stop LIST from blocking...
   Highest priority: Resources.

DOCS:

 * Base information: RFC0959
 * Security: RFC2577
"""

from __future__ import nested_scopes

# System Imports
import os
import time
import string
import types
import re
import StringIO
from math import floor

# Twisted Imports
from twisted.internet import abstract, reactor, protocol, error
from twisted.internet.interfaces import IProducer, IConsumer, IProtocol, IFinishableConsumer
from twisted.protocols import basic
from twisted.internet.protocol import ClientFactory, ServerFactory, Protocol, \
                                      ConsumerToProtocolAdapter
from twisted import internet
from twisted.internet.defer import Deferred, DeferredList, FAILURE
from twisted.python.failure import Failure
from twisted.python import log, components


# the replies from the ftp server
# a 3-digit number identifies the meaning
# used by Ftp.reply(key)
ftp_reply = {
    'file':      '150 File status okay; about to open data connection.',

    'type':      '200 Type set to %s.',
    'ok':        '200 %s command successful.',
    'size':      '213 %s',
    'syst':      '215 UNIX Type: L8',
    'abort':     '226 Abort successful',
    'welcome':   '220 Welcome, twisted.ftp at your service.',
    'goodbye':   '221 Goodbye.',
    'fileok':    '226 Transfer Complete.',
    'epsv':      '229 Entering Extended Passive Mode (|||%s|).',
    'cwdok':     '250 CWD command successful.',
    'pwd':       '257 "%s" is current directory.',

    'user':      '331 Password required for %s.',
    'userotp':   '331 Response to %s.',
    'guest':     '331 Guest login ok, type your name as password.',
    'userok':    '230 User %s logged in.',
    'guestok':   '230 Guest login ok, access restrictions apply.',

    'getabort':  '426 Transfer aborted.  Data connection closed.',
    'unknown':   "500 '%s': command not understood.",
    'nouser':    '503 Login with USER first.',
    'notimpl':   '504 Not implemented.',
    'nopass':    '530 Please login with USER and PASS.',
    'noauth':    '530 Sorry, Authentication failed.',
    'nodir':     '550 %s: No such file or directory.',
    'noperm':    '550 %s: Permission denied.'
    }



class SendFileTransfer:
    "Producer, server to client"
    
    request = None
    file = None
    filesize = None
    
    __implements__ = IProducer
    
    def __init__(self, file, filesize, request):
        self.request = request
        self.file = file
        self.filesize = filesize
        request.registerProducer(self, 0) # TODO: Dirty
    
    def resumeProducing(self):
        if (self.request is None) or (self.file.closed):
            return
        buffer = self.file.read(abstract.FileDescriptor.bufferSize)
        self.request.write(buffer)

        if self.file.tell() == self.filesize:
            self.stopProducing()
                    
    def pauseProducing(self):
        pass

    def stopProducing(self):
        self.request.unregisterProducer()
        #reactor.callLater(0, self.request.finish)
        self.request.finish()
        self.request = None


class DTP(protocol.Protocol):
    """A Client/Server-independent implementation of the DTP-protocol.
    Performs the actions RETR, STOR and LIST. The data transfer will
    start as soon as:
    1) The user has connected 2) the property 'action' has been set. 
    """
    # PI is the telnet-like interface to FTP
    # Will be set to the instance which initiates DTP
    pi = None
    file = None
    filesize = None
    action = ""

    def executeAction(self):
        """Initiates a transfer of data.
        Its action is based on self.action, and self.pi.queuedfile
        """
        func = getattr(self, 'action' + self.action, None)
        if func:
            func(self.pi.queuedfile)

    def connectionMade(self):
        "Will start an transfer, if one is queued up, when the client connects"
        self.dtpPort = self.pi.dtpPort
        if self.action:
            self.executeAction()

    def setAction(self, action):
        "Set the action, and if the connected, start the transfer"
        self.action = action
        if self.transport is not None:
            self.executeAction()

    def connectionLost(self, reason):
        if (self.action == 'STOR') and (self.file):
            self.pi.reply('fileok')
        elif self.file is not None:
            if self.file.tell() == self.filesize:
                self.pi.reply('fileok')
            else:
                self.pi.reply('getabort')
        if self.file is not None:
            self.file.close()

            self.file = None
        self.pi.queuedfile = None
        self.action = None
        if hasattr(self.dtpPort, 'loseConnection'):
            self.dtpPort.loseConnection()
        else:
            self.dtpPort.disconnect()

    #
    #   "RETR"
    #
    def finishRETR(self):
        """Disconnect, and clean up a RETR
        Called by producer when the transfer is done
        """
        self.transport.loseConnection()

    def makeRETRTransport(self):
        transport = self.transport
        transport.finish = self.finishRETR
        return transport
        
    def actionRETR(self, queuedfile):
        "Send the given file to the peer"
        if self.file is None:
            self.file = open(queuedfile, "rb")
            self.filesize = os.path.getsize(queuedfile)
        producer = SendFileTransfer(self.file, self.filesize, self.makeRETRTransport())
        producer.resumeProducing()

    #
    #   "STOR"
    #
    def dataReceived(self, data):
        if (self.action == 'STOR') and (self.file):
            self.file.write(data)
            self.file.flush()
            self.filesize = self.filesize + len(data)

    def makeSTORTransport(self):
        transport = self.transport
        return transport
        
    def actionSTOR(self, queuedfile):
        "Retrieve a file from peer"
        self.file = open(queuedfile, "wb")
        self.filesize = 0
        transport = self.makeSTORTransport()

    #
    #   'LIST'
    #
    def actionLIST(self, dir):
        """Prints outs the files in the given directory
        Note that the printout is very fake, and only gives the filesize,
        date, time and filename.
        """
        list = os.listdir(dir)
        s = ''
        for a in list:
            ts = a
            ff = os.path.join(dir, ts) # the full filename
            try:
                # os.path.getmtime calls os.stat: os.stat fails w/ an IOError
                # on broken symlinks.  I know there's some way to get the real
                # mtime out, since ls does it, but I haven't had time to figure
                # out how to do it from python.
                mtn = os.path.getmtime(ff)
                fsize = os.path.getsize(ff)
            except OSError:
                mtn = 0
                fsize = 0
            mtime = time.strftime("%b %d %H:%M", time.gmtime(mtn))
            if os.path.isdir(ff):
                diracc = 'd'
            else:
                diracc = '-'    
            s = s + diracc+"r-xr-xr-x    1 twisted twisted %11d" % fsize+' '+mtime+' '+ts+'\r\n'
        self.action = 'RETR'
        self.file = StringIO.StringIO(s)
        self.filesize = len(s)
        #reactor.callLater(0.1, self.executeAction)
        self.executeAction()

    #
    #   'NLST'
    #
    def actionNLST(self, dir):
        s = '\r\n'.join(os.listdir(dir))
        self.file = StringIO.StringIO(s)
        self.filesize = len(s)
        self.action = 'RETR'
        self.executeAction()
        #reactor.callLater(0.1, self.executeAction)
        

class DTPFactory(protocol.ClientFactory):
    """The DTP-Factory.
    This class is not completely self-contained.
    """
    dtpClass = DTP
    dtp = None      # The DTP-protocol
    dtpPort = None  # The TCPClient / TCPServer
    action = None

    def createPassiveServer(self):
        if self.dtp is not None:
            if self.dtp.transport is not None:
                self.dtp.transport.loseConnection()
            self.dtp = None
        # giving 0 will generate a free port
        self.dtpPort = reactor.listenTCP(0, self)
 
    def createActiveServer(self):
        if self.dtp is not None:
            if self.dtp.transport is not None:
                self.dtp.transport.loseConnection()
            self.dtp = None
        self.dtpPort = reactor.connectTCP(self.peerhost, self.peerport, self)

    def buildProtocol(self,addr):
        p = self.dtpClass()
        p.factory = self
        p.pi = self
        self.dtp = p
        if self.action is not None:
            self.dtp.setAction(self.action)
            self.action = None
        return p

class FTP(basic.LineReceiver, DTPFactory):
    """An FTP server.
    
    This class is unstable (it will be heavily refactored to support dynamic
    content, etc)."""
    user   = None
    passwd = None
    root   = None
    wd     = None # Working Directory
    type   = None
    peerhost = None
    peerport = None
    queuedfile = None
    debug = 0           # Are all the print statements necessary anymore?

    def setAction(self, action):
        """Alias for DTP.setAction
        Since there's no guarantee an instance of dtp exists"""
        if self.dtp is not None:
            self.dtp.setAction(action)
        else:
            self.action = action

    def reply(self, key, s = ''):
        if string.find(ftp_reply[key], '%s') > -1:
            if self.debug:
                log.msg(ftp_reply[key] % s + '\r\n')
            self.transport.write(ftp_reply[key] % s + '\r\n')
        else:
            if self.debug:
                log.msg(ftp_reply[key] + '\r\n')
            self.transport.write(ftp_reply[key] + '\r\n')

    # This command is IMPORTANT! Must also get rid of it :)
    def checkauth(self):
        """Will return None if the user has been authorized
        This must be run in front of all commands except USER, PASS and QUIT
        """
        if None in [self.user, self.passwd]:
            self.reply('nopass')
            return 1
        else:
            return None
        
    def connectionMade(self):
        self.reply('welcome')

    def ftp_Quit(self, params):
        self.reply('goodbye')
        self.transport.loseConnection()
    
    def ftp_User(self, params):
        """Get the login name, and reset the session
        PASS is expected to follow
        """
        if params=='':
            return 1
        self.user = string.split(params)[0]
        if self.factory.anonymous and self.user == self.factory.useranonymous:
            self.reply('guest')
            self.root = self.factory.root
            self.wd = '/'
        else:
            # TODO:
            # Add support for home-dir
            if self.factory.otp:
                otp = self.factory.userdict[self.user]["otp"]
                prompt = otp.challenge()
                otpquery = "Response to %s %s for skey" % (prompt, "required")
                self.reply('userotp', otpquery)
            else:
                self.reply('user', self.user)
            self.root = self.factory.root
            self.wd = '/'
        # Flush settings
        self.passwd = None
        self.type = 'A'
            
    def ftp_Pass(self, params):
        """Authorize the USER and the submitted password
        """
        if not self.user:
            self.reply('nouser')
            return
        
        if self.factory.anonymous and self.user == self.factory.useranonymous:
            self.passwd = params
            self.reply('guestok')
        else:
            # Authing follows
            if self.factory.otp:
                otp = self.factory.userdict[self.user]["otp"]
                try:
                    otp.authenticate(self.passwd)
                    self.passwd = params
                    self.reply('userok', self.user)
                except:
                    self.reply('noauth')
            else:
                if (self.factory.userdict.has_key(self.user)) and \
                   (self.factory.userdict[self.user]["passwd"] == params):
                    self.passwd = params
                    self.reply('userok', self.user)
                else:
                    self.reply('noauth')

    def ftp_Noop(self, params):
        """Do nothing, and reply an OK-message
        Sometimes used by clients to avoid a time-out.
        TODO: Add time-out, let Noop extend this time-out.
        Add a No-Transfer-Time-out as well to get rid of idlers.
        """
        if self.checkauth(): return
        self.reply('ok', 'NOOP')

    def ftp_Syst(self, params):
        """Return the running operating system to the client
        However, due to security-measures, it will return a standard 'L8' reply
        """
        if self.checkauth(): return
        self.reply('syst')
        
    def ftp_Pwd(self, params):
        if self.checkauth(): return
        self.reply('pwd', self.wd)

    def ftp_Cwd(self, params):
        if self.checkauth(): return
        wd = os.path.normpath(params)
        if not os.path.isabs(wd):
            wd = os.path.normpath(self.wd + '/' + wd)
        wd = string.replace(wd, '\\','/')
        while string.find(wd, '//') > -1:
            wd = string.replace(wd, '//','/')
        # '..', '\\', and '//' is there just to prevent stop hacking :P
        if (not os.path.isdir(self.root + wd)) or (string.find(wd, '..') > 0) or \
            (string.find(wd, '\\') > 0) or (string.find(wd, '//') > 0): 
            self.reply('nodir', params)
            return
        else:
            wd = string.replace(wd, '\\','/')
            self.wd = wd
            self.reply('cwdok')

    def ftp_Cdup(self, params):
        self.ftp_Cwd('..')

    def ftp_Type(self, params):
        if self.checkauth(): return
        params = string.upper(params)
        if params in ['A', 'I']:
            self.type = params
            self.reply('type', self.type)
        else:
            return 1

    def ftp_Port(self, params):
        """Request for an active connection
        This command may be potentially abused, and the only countermeasure
        so far is that no port below 1024 may be targeted.
        An extra approach is to disable port'ing to a third-party ip,
        which is optional through ALLOW_THIRDPARTY.
        Note that this disables 'Cross-ftp' 
        """
        if self.checkauth(): return
        params = string.split(params, ',')
        if not (len(params) in [6]): return 1
        peerhost = string.join(params[:4], '.') # extract ip
        peerport = int(params[4])*256+int(params[5])
        # Simple countermeasurements against bouncing
        if peerport < 1024:
            self.reply('notimpl')
            return
        if not self.factory.thirdparty:
            sockname = self.transport.getPeer()
            if not (peerhost == sockname[1]):
                self.reply('notimpl')
                return
        self.peerhost = peerhost
        self.peerport = peerport
        self.createActiveServer()
        self.reply('ok', 'PORT')

    def ftp_Pasv(self, params):
        "Request for a passive connection"
        if self.checkauth():
            return
        self.createPassiveServer()
        # Use the ip from the pi-connection
        sockname = self.transport.getHost()
        localip = string.replace(sockname[1], '.', ',')
        lport = self.dtpPort.socket.getsockname()[1]
        lp1 = lport / 256
        lp2, lp1 = str(lport - lp1*256), str(lp1)
        self.transport.write('227 Entering Passive Mode ('+localip+
                             ','+lp1+','+lp2+')\r\n')

    def ftp_Epsv(self, params):
        "Request for a Extended Passive connection"
        if self.checkauth(): 
            return
        self.createPassiveServer()
        self.reply('epsv', `self.dtpPort.socket.getsockname()[1]`)

    def buildFullpath(self, rpath):
        """Build a new path, from a relative path based on the current wd
        This routine is not fully tested, and I fear that it can be
        exploited by building clever paths
        """
        npath = os.path.normpath(rpath)
#        if npath == '':
#            npath = '/'
        if not os.path.isabs(npath):
            npath = os.path.normpath(self.wd + '/' + npath)
        npath = self.root + npath
        return os.path.normpath(npath) # finalize path appending 

    def ftp_Size(self, params):
        if self.checkauth():
            return
        npath = self.buildFullpath(params)
        if not os.path.isfile(npath):
            self.reply('nodir', params)
            return
        self.reply('size', os.path.getsize(npath))

    def ftp_Dele(self, params):
        if self.checkauth():
            return
        npath = self.buildFullpath(params)
        if not os.path.isfile(npath):
            self.reply('nodir', params)
            return
        os.remove(npath)
        self.reply('fileok')

    def ftp_Mkd(self, params):
        if self.checkauth():
            return
        npath = self.buildFullpath(params)
        try:
            os.mkdir(npath)
            self.reply('fileok')
        except IOError:
            self.reply('nodir')

    def ftp_Rmd(self, params):
        if self.checkauth():
            return
        npath = self.buildFullpath(params)
        if not os.path.isdir(npath):
            self.reply('nodir', params)
            return
        try:
            os.rmdir(npath)
            self.reply('fileok')
        except IOError:
            self.reply('nodir')
 
    def ftp_List(self, params):
        self.getListing(params)

    def ftp_Nlst(self, params):
        self.getListing(params, 'NLST')

    def getListing(self, params, action='LIST'):
        if self.checkauth():
            return
        if self.dtpPort is None:
            self.reply('notimpl')   # and will not be; standard noauth-reply
            return
        if params == "-a": params = '' # bug in konqueror
        # The reason for this long join, is to exclude access below the root
        npath = self.buildFullpath(params)
        if not os.path.isdir(npath):
            self.reply('nodir', params)
            return
        if not os.access(npath, os.O_RDONLY):
            self.reply('noperm', params)
            return
        self.reply('file')
        self.queuedfile = npath 
        self.setAction(action)
 
    def ftp_Retr(self, params):
        if self.checkauth():
            return
        npath = self.buildFullpath(params)
        if not os.path.isfile(npath):
            self.reply('nodir', params)
            return
        if not os.access(npath, os.O_RDONLY):
            self.reply('noperm', params)
            return
        self.reply('file')
        self.queuedfile = npath 
        self.setAction('RETR')

    def ftp_Stor(self, params):
        if self.checkauth():
            return
        # The reason for this long join, is to exclude access below the root
        npath = self.buildFullpath(params)
        if os.path.isfile(npath):
            # Insert access for overwrite here :)
            #self.reply('nodir', params)
            pass
        self.reply('file')
        self.queuedfile = npath 
        self.setAction('STOR')

    def ftp_Abor(self, params):
        if self.checkauth():
            return
        if self.dtp.transport.connected:
            self.dtp.finishGet() # not 100 % perfect on uploads
        self.reply('abort')

    def lineReceived(self, line):
        "Process the input from the client"
        line = string.strip(line)
        if self.debug:
            log.msg(repr(line))
        command = string.split(line)
        if command == []:
            self.reply('unknown')
            return 0
        commandTmp, command = command[0], ''
        for c in commandTmp:
            if ord(c) < 128:
                command = command + c
        command = string.capitalize(command)
        if self.debug:
            log.msg("-"+command+"-")
        if command == '':
            return 0
        if string.count(line, ' ') > 0:
            params = line[string.find(line, ' ')+1:]
        else:
            params = ''
        # Does this work at all? Quit at ctrl-D
        if ( string.find(line, "\x1A") > -1):
            command = 'Quit'
        method = getattr(self, "ftp_%s" % command, None)
        if method is not None:
            n = method(params)
            if n == 1:
                self.reply('unknown', string.upper(command))
        else:
            self.reply('unknown', string.upper(command))


class FTPFactory(protocol.Factory):
    command = ''
    userdict = {}
    anonymous = 1
    thirdparty = 0
    otp = 0
    root = '/var/www'
    useranonymous = 'anonymous'
 
    def buildProtocol(self, addr):
        p=FTP()
        p.factory = self
        return p


    
####
# And now for the client...

# Notes:
#   * Reference: http://cr.yp.to/ftp.html
#   * FIXME: Does not support pipelining (which is not supported by all
#     servers anyway).  This isn't a functionality limitation, just a
#     small performance issue.
#   * Only has a rudimentary understanding of FTP response codes (although
#     the full response is passed to the caller if they so choose).
#   * Assumes that USER and PASS should always be sent
#   * Always sets TYPE I  (binary mode)
#   * Doesn't understand any of the weird, obscure TELNET stuff (\377...)
#   * FIXME: Doesn't share any code with the FTPServer

class FTPError(Exception):
    pass

class ConnectionLost(FTPError):
    pass

class CommandFailed(FTPError):
    pass

class BadResponse(FTPError):
    pass

class UnexpectedResponse(FTPError):
    pass

class FTPCommand:
    def __init__(self, text=None, public=0):
        self.text = text
        self.deferred = Deferred()
        self.ready = 1
        self.public = public

    def fail(self, failure):
        if self.public:
            self.deferred.errback(failure)


class ProtocolWrapper(Protocol):
    def __init__(self, original, deferred):
        self.original = original
        self.deferred = deferred
    def makeConnection(self, transport):
        self.original.makeConnection(transport)
    def dataReceived(self, data):
        self.original.dataReceived(data)
    def connectionLost(self, reason):
        self.original.connectionLost(reason)
        # Signal that transfer has completed
        self.deferred.callback(None)
    def connectionFailed(self):
        self.deferred.errback(Failure(FTPError('Connection failed')))


class SenderProtocol(Protocol):
    __implements__ = Protocol.__implements__ + (IFinishableConsumer,)

    def __init__(self):
        # Fired upon connection
        self.connectedDeferred = Deferred()

        # Fired upon disconnection
        self.deferred = Deferred()

    #Protocol stuff
    def dataReceived(self, data):
        assert 0, ("We received data from the server - "
                   "this shouldn't happen.")

    def makeConnection(self, transport):
        Protocol.makeConnection(self, transport)
        self.connectedDeferred.callback(self)
        
    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            self.deferred.callback('connection done')
        else:
            self.deferred.errback(reason)

    #IFinishableConsumer stuff
    def write(self, data):
        self.transport.write(data)

    def registerProducer(self):
        pass

    def unregisterProducer(self):
        pass

    def finish(self):
        self.transport.loseConnection()
    
    
def decodeHostPort(line):
    """Decode an FTP response specifying a host and port.

    @returns: a 2-tuple of (host, port).
    """
    abcdef = re.sub('[^0-9, ]', '', line[4:])
    a, b, c, d, e, f = map(str.strip, abcdef.split(','))
    host = "%s.%s.%s.%s" % (a, b, c, d)
    port = (int(e)<<8) + int(f)
    return host, port


class FTPDataPortFactory(ServerFactory):
    """Factory for data connections that use the PORT command
    
    (i.e. "active" transfers)
    """
    noisy = 0
    def buildProtocol(self, connection):
        # This is a bit hackish -- we already have a Protocol instance,
        # so just return it instead of making a new one
        # FIXME: Reject connections from the wrong address/port
        #        (potential security problem)
        self.protocol.factory = self
        self.port.loseConnection()
        return self.protocol


class FTPClient(basic.LineReceiver):
    """A Twisted FTP Client

    Supports active and passive transfers.

    This class is semi-stable.

    @ivar passive: See description in __init__.
    """
    debug = 0
    def __init__(self, username='anonymous', 
                 password='twisted@twistedmatrix.com',
                 passive=1):
        """Constructor.

        I will login as soon as I receive the welcome message from the server.

        @param username: FTP username
        @param password: FTP password
        @param passive: flag that controls if I use active or passive data
            connections.  You can also change this after construction by
            assigning to self.passive.
        """
        self.username = username
        self.password = password

        self.actionQueue = []
        self.nextDeferred = None
        self.queueLogin()
        self.response = []

        self.passive = passive

    def fail(self, error):
        """Disconnect, and also give an error to any queued deferreds."""
        self.transport.loseConnection()
        while self.actionQueue:
            ftpCommand = self.popCommandQueue()
            ftpCommand.fail(Failure(ConnectionLost('FTP connection lost', error)))
        return error

    def sendLine(self, line):
        """(Private) Sends a line, unless line is None."""
        if line is None:
            return
        basic.LineReceiver.sendLine(self, line)

    def sendNextCommand(self):
        """(Private) Processes the next command in the queue."""
        ftpCommand = self.popCommandQueue()
        if ftpCommand is None:
            self.nextDeferred = None
            return
        if not ftpCommand.ready:
            self.actionQueue.insert(0, ftpCommand)
            reactor.callLater(1.0, self.sendNextCommand)
            self.nextDeferred = None
            return
        if ftpCommand.text == 'PORT':
            self.generatePortCommand(ftpCommand)
        if self.debug:
            log.msg('<-- %s' % ftpCommand.text)
        self.nextDeferred = ftpCommand.deferred
        self.sendLine(ftpCommand.text)

    def queueLogin(self):
        """Initialise the connection.

        Login, send the password, set retrieval mode to binary"""
        self.nextDeferred = Deferred().addErrback(self.fail)
        for command in ('USER ' + self.username, 
                        'PASS ' + self.password,
                        'TYPE I',):
            d = self.queueStringCommand(command, public=0)
            # If something goes wrong, call fail
            d.addErrback(self.fail)
            # But also swallow the error, so we don't cause spurious errors
            d.addErrback(lambda x: None)
        
    def queueCommand(self, ftpCommand):
        """Add an FTPCommand object to the queue.

        If it's the only thing in the queue, and we are connected and we aren't
        waiting for a response of an earlier command, the command will be sent
        immediately.

        @param ftpCommand: an L{FTPCommand}
        """
        self.actionQueue.append(ftpCommand)
        if (len(self.actionQueue) == 1 and self.transport is not None and
            self.nextDeferred is None):
            self.sendNextCommand()

    def popCommandQueue(self):
        """Return the front element of the command queue, or None if empty."""
        if self.actionQueue:
            return self.actionQueue.pop(0)
        else:
            return None

    def receiveFromConnection(self, command, protocol):
        """
        Retrieves a file or listing generated by the given command,
        feeding it to the given protocol.

        @param command: string of an FTP command to execute then receive the
            results of (e.g. LIST, RETR)
        @param protocol: A L{Protocol} *instance* e.g. an
            L{FTPFileListProtocol}, or something that can be adapted to one.
            Typically this will be an L{IConsumer} implemenation.

        @returns: L{Deferred}.
        """
        protocol = IProtocol(protocol)
        wrapper = ProtocolWrapper(protocol, Deferred())
        return self._openDataConnection(command, wrapper)

    def sendToConnection(self, command):
        """XXX
        
        @returns: A tuple of two L{Deferred}s:
                  - L{Deferred} L{IFinishableConsumer}. You must call
                    the C{finish} method on the IFinishableConsumer when the file
                    is completely transferred.
                  - L{Deferred} list of control-connection responses.
        """
        s = SenderProtocol()
        r = self._openDataConnection(command, s)
        return (s.connectedDeferred, r)

    def _openDataConnection(self, command, protocol):
        """
        This method returns a DeferredList.
        """
        cmd = FTPCommand(command, public=1)

        if self.passive:
            # Hack: use a mutable object to sneak a variable out of the 
            # scope of doPassive
            _mutable = [None]
            def doPassive(response):
                """Connect to the port specified in the response to PASV"""
                host, port = decodeHostPort(response[-1])

                class _Factory(ClientFactory):
                    noisy = 0
                    def buildProtocol(self, ignored):
                        self.protocol.factory = self
                        return self.protocol
                    def clientConnectionFailed(self, connector, reason):
                        self.protocol.connectionFailed()
                f = _Factory()
                f.protocol = protocol
                _mutable[0] = reactor.connectTCP(host, port, f)

            pasvCmd = FTPCommand('PASV')
            self.queueCommand(pasvCmd)
            pasvCmd.deferred.addCallback(doPassive).addErrback(self.fail)

            results = [cmd.deferred, pasvCmd.deferred, protocol.deferred]
            d = DeferredList(results, fireOnOneErrback=1)

            # Ensure the connection is always closed
            def close(x, m=_mutable):
                m[0] and m[0].disconnect()
                return x
            d.addBoth(close)

        else:
            # We just place a marker command in the queue, and will fill in
            # the host and port numbers later (see generatePortCommand)
            portCmd = FTPCommand('PORT')

            # Ok, now we jump through a few hoops here.
            # This is the problem: a transfer is not to be trusted as complete
            # until we get both the "226 Transfer complete" message on the 
            # control connection, and the data socket is closed.  Thus, we use
            # a DeferredList to make sure we only fire the callback at the 
            # right time.

            portCmd.transferDeferred = protocol.deferred
            portCmd.protocol = protocol
            portCmd.deferred.addErrback(portCmd.transferDeferred.errback)
            self.queueCommand(portCmd)

            # Create dummy functions for the next callback to call.
            # These will also be replaced with real functions in 
            # generatePortCommand.
            portCmd.loseConnection = lambda result: result
            portCmd.fail = lambda error: error
            
            # Ensure that the connection always gets closed
            cmd.deferred.addErrback(lambda e, pc=portCmd: pc.fail(e) or e)

            results = [cmd.deferred, portCmd.deferred, portCmd.transferDeferred]
            d = DeferredList(results, fireOnOneErrback=1)
                              
        self.queueCommand(cmd)
        return d

    def generatePortCommand(self, portCmd):
        """(Private) Generates the text of a given PORT command"""

        # The problem is that we don't create the listening port until we need
        # it for various reasons, and so we have to muck about to figure out
        # what interface and port it's listening on, and then finally we can
        # create the text of the PORT command to send to the FTP server.

        # FIXME: This method is far too ugly.

        # FIXME: The best solution is probably to only create the data port
        #        once per FTPClient, and just recycle it for each new download.
        #        This should be ok, because we don't pipeline commands.
        
        # Start listening on a port
        factory = FTPDataPortFactory()
        factory.protocol = portCmd.protocol
        listener = reactor.listenTCP(0, factory)
        factory.port = listener

        # Ensure we close the listening port if something goes wrong
        def listenerFail(error, listener=listener):
            if listener.connected:
                listener.loseConnection()
            return error
        portCmd.fail = listenerFail

        # Construct crufty FTP magic numbers that represent host & port
        host = self.transport.getHost()[1]
        port = listener.getHost()[2]
        numbers = string.split(host, '.') + [str(port >> 8), str(port % 256)]
        portCmd.text = 'PORT ' + string.join(numbers,',')

    def escapePath(self, path):
        """Returns a FTP escaped path (replace newlines with nulls)"""
        # Escape newline characters
        return string.replace(path, '\n', '\0')

    def retrieveFile(self, path, protocol):
        """Retrieve a file from the given path

        This method issues the 'RETR' FTP command.
        
        The file is fed into the given Protocol instance.  The data connection
        will be passive if self.passive is set.

        @param path: path to file that you wish to receive.
        @param protocol: a L{Protocol} instance.

        @returns: L{Deferred}
        """
        return self.receiveFromConnection('RETR ' + self.escapePath(path), protocol)

    retr = retrieveFile

    def storeFile(self, path):
        """Store a file at the given path.

        This method issues the 'STOR' FTP command.

        @returns: A tuple of two L{Deferred}s:
                  - L{Deferred} L{IFinishableConsumer}. You must call
                    the C{finish} method on the IFinishableConsumer when the file
                    is completely transferred.
                  - L{Deferred} list of control-connection responses.
        """
        
        return self.sendToConnection('STOR ' + self.escapePath(path))

    stor = storeFile
        
    def list(self, path, protocol):
        """Retrieve a file listing into the given protocol instance.

        This method issues the 'LIST' FTP command.

        @param path: path to get a file listing for.
        @param protocol: a L{Protocol} instance, probably a
            L{FTPFileListProtocol} instance.  It can cope with most common file
            listing formats.

        @returns: L{Deferred}
        """
        if path is None:
            path = ''
        return self.receiveFromConnection('LIST ' + self.escapePath(path), protocol)
        
    def nlst(self, path, protocol):
        """Retrieve a short file listing into the given protocol instance.

        This method issues the 'NLST' FTP command.
        
        NLST (should) return a list of filenames, one per line.

        @param path: path to get short file listing for.
        @param protocol: a L{Protocol} instance.
        """
        if path is None:
            path = ''
        return self.receiveFromConnection('NLST ' + self.escapePath(path), protocol)

    def queueStringCommand(self, command, public=1):
        """Queues a string to be issued as an FTP command
        
        @param command: string of an FTP command to queue
        @param public: a flag intended for internal use by FTPClient.  Don't
            change it unless you know what you're doing.
        
        @returns: a L{Deferred} that will be called when the response to the
        command has been received.
        """
        ftpCommand = FTPCommand(command, public)
        self.queueCommand(ftpCommand)
        return ftpCommand.deferred

    def cwd(self, path):
        """Issues the CWD (Change Working Directory) command.

        @returns: a L{Deferred} that will be called when done.
        """
        return self.queueStringCommand('CWD ' + self.escapePath(path))

    def cdup(self):
        """Issues the CDUP (Change Directory UP) command.

        @returns: a L{Deferred} that will be called when done.
        """
        return self.queueStringCommand('CDUP')

    def pwd(self):
        """Issues the PWD (Print Working Directory) command.

        @returns: a L{Deferred} that will be called when done.  It is up to the 
            caller to interpret the response, but the L{parsePWDResponse} method
            in this module should work.
        """
        return self.queueStringCommand('PWD')

    def quit(self):
        """Issues the QUIT command."""
        return self.queueStringCommand('QUIT')
    
    def lineReceived(self, line):
        """(Private) Parses the response messages from the FTP server."""
        # Add this line to the current response
        if self.debug:
            log.msg('--> %s' % line)
        line = string.rstrip(line)
        self.response.append(line)

        code = line[0:3]
        
        # Bail out if this isn't the last line of a response
        # The last line of response starts with 3 digits followed by a space
        codeIsValid = len(filter(lambda c: c in '0123456789', code)) == 3
        if not (codeIsValid and line[3] == ' '):
            return

        # Ignore marks
        if code[0] == '1':
            return

        # Check that we were expecting a response
        if self.nextDeferred is None:
            self.fail(UnexpectedResponse(self.response))
            return

        # Reset the response
        response = self.response
        self.response = []

        # Look for a success or error code, and call the appropriate callback
        if code[0] in ('2', '3'):
            # Success
            self.nextDeferred.callback(response)
        elif code[0] in ('4', '5'):
            # Failure
            self.nextDeferred.errback(Failure(CommandFailed(response)))
        else:
            # This shouldn't happen unless something screwed up.
            log.msg('Server sent invalid response code %s' % (code,))
            self.nextDeferred.errback(Failure(BadResponse(response)))
            
        # Run the next command
        self.sendNextCommand()
        

class FTPFileListProtocol(basic.LineReceiver):
    """Parser for standard FTP file listings
    
    This is the evil required to match::

        -rw-r--r--   1 root     other        531 Jan 29 03:26 README

    If you need different evil for a wacky FTP server, you can override this.

    It populates the instance attribute self.files, which is a list containing
    dicts with the following keys (examples from the above line):
        - filetype: e.g. 'd' for directories, or '-' for an ordinary file
        - perms:    e.g. 'rw-r--r--'
        - owner:    e.g. 'root'
        - group:    e.g. 'other'
        - size:     e.g. 531
        - date:     e.g. 'Jan 29 03:26'
        - filename: e.g. 'README'

    Note that the 'date' value will be formatted differently depending on the
    date.  Check U{http://cr.yp.to/ftp.html} if you really want to try to parse
    it.

    @ivar files: list of dicts describing the files in this listing
    """
    fileLinePattern = re.compile(
        r'^(?P<filetype>.)(?P<perms>.{9})\s+\d*\s*'
        r'(?P<owner>\S+)\s+(?P<group>\S+)\s+(?P<size>\d+)\s+'
        r'(?P<date>... .. ..:..)\s+(?P<filename>.*?)\r?$'
    )
    delimiter = '\n'

    def __init__(self):
        self.files = []

    def lineReceived(self, line):
        match = self.fileLinePattern.match(line)
        if match:
            dict = match.groupdict()
            dict['size'] = int(dict['size'])
            self.files.append(dict)



def parsePWDResponse(response):
    """Returns the path from a response to a PWD command.

    Responses typically look like::

        257 "/home/andrew" is current directory.

    For this example, I will return C{'/home/andrew'}.

    If I can't find the path, I return C{None}.
    """
    match = re.search('".*"', response)
    if match:
        return match.groups()[0]
    else:
        return None
