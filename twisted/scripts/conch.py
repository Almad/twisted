
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
# $Id: conch.py,v 1.3 2002/11/07 23:01:15 z3p Exp $

#""" Implementation module for the `ssh` command.
#"""

from twisted.conch.ssh import transport, userauth, connection, common, keys
from twisted.internet import reactor, stdio, defer, protocol
from twisted.python import usage, log

import os, sys, getpass, struct, tty, fcntl

class GeneralOptions(usage.Options):
    synopsis = """Usage:    ssh [options] host [command]
 """

    optParameters = [['user', 'l', None, 'Log in using this user name.'],
                  ['identity', 'i', '~/.ssh/identity', 'Identity for public key authentication'],
                  ['cipher', 'c', None, 'Select encryption algorithm.'],
                  ['macs', 'm', None, 'Specify MAC algorithms for protocol version 2.'],
                  ['port', 'p', None, 'Connect to this port.  Server must be on the same port.']]
                  
    
    optFlags = [['null', 'n', 'Redirect input from /dev/null.'],
                ['tty', 't', 'Tty; allocate a tty even if command is given.'],
                ['notty', 'T', 'Do not allocate a tty.'],
                ['version', 'V', 'Display version number only.'],
                ['compress', 'C', 'Enable compression.'],
                ['noshell', 'N', 'Do not execute a shell or command.'],
                ['subsystem', 's', 'Invoke command (mandatory) as SSH2 subsystem.'],
                ['log', '', 'Log to stderr']]

    identitys = ['~/.ssh/id_rsa', '~/.ssh/id_dsa']

    def opt_identity(self, i):
        self.identitys.append(i)

    def parseArgs(self, host, *command):
        self['host'] = host
        self['command'] = ' '.join(command)

# Rest of code in "run"
options = {}
exitStatus = 0

def run():
    global options
    args = sys.argv[1:]
    if '-l' in args: # cvs is an idiot
        i = args.index('-l')
        args = args[i:i+2]+args
        del args[i+2:i+4]
    options = GeneralOptions()
    try:
        options.parseOptions(args)
    except usage.UsageError, u:
        print 'ERROR: %s' % u
        options.opt_help()
        sys.exit(1)
    if options['log']:
        realout = sys.stdout
        log.startLogging(sys.stderr)
        sys.stdout = realout
    else:
        log.discardLogs()
    if '@' in options['host']:
        options['user'], options['host'] = options['host'].split('@',1)
    host = options['host']
    port = int(options['port'] or 22)
    log.msg(str((host,port)))
    reactor.connectTCP(host, port, SSHClientFactory())
    fd = sys.stdin.fileno()
    try:
        old = tty.tcgetattr(fd)
    except:
        old = None
    try:
        reactor.run()
    finally:
        if old:
            tty.tcsetattr(fd, tty.TCSADRAIN, old)
    sys.exit(exitStatus)

class SSHClientFactory(protocol.ClientFactory):
    noisy = 1 

    def stopFactory(self):
        reactor.stop()

    def buildProtocol(self, addr):
        return SSHClientTransport()

class SSHClientTransport(transport.SSHClientTransport):
    def connectionSecure(self):
        if options['user']:
            user = options['user']
        else:
            user = getpass.getuser()
        self.requestService(SSHUserAuthClient(user, SSHConnection()))

class SSHUserAuthClient(userauth.SSHUserAuthClient):
    usedFiles = []

    def getPassword(self, prompt = None):
#        self.passDeferred = defer.Deferred()
        if not prompt:
            prompt = "%s@%s's password: " % (self.user, options['host'])
        #return self.passDeferred
        oldout, oldin = sys.stdout, sys.stdin
        sys.stdin = sys.stdout = open('/dev/tty','r+')
        p=getpass.getpass(prompt)
        sys.stdout,sys.stdin=oldout,oldin
        return defer.succeed(p)
        

    def gotPassword(self, q, password):
        d = self.passDeferred
        del self.passDeferred
        d.callback(password)

    def getPublicKey(self):
        files = [x for x in options.identitys if x not in self.usedFiles]
        if not files:
            return None
        file = files[0]
        log.msg(file)
        self.usedFiles.append(file)
        file = os.path.expanduser(file) 
        file += '.pub'
        if not os.path.exists(file):
            return
        return keys.getPublicKeyString(file) 
    
    def getPrivateKey(self):
# doesn't handle encryption
        file = os.path.expanduser(self.usedFiles[-1])
        if not os.path.exists(file):
            return None
        return keys.getPrivateKeyObject(file)

class SSHConnection(connection.SSHConnection):
    def serviceStarted(self):
# port forwarding will go here
        if not options['notty']:
            self.openChannel(SSHSession(1048576, 4294967295L))

class SSHSession(connection.SSHChannel):
    name = 'session'
    
    def channelOpen(self, foo):
        # turn off local echo
        fd = sys.stdin.fileno()
        try:
            new = tty.tcgetattr(fd)
        except:
            log.msg('not a typewriter!') 
        else:
            new[3] = new[3] & ~tty.ICANON & ~tty.ECHO
            new[6][tty.VMIN] = 1
            new[6][tty.VTIME] = 0
            tty.tcsetattr(fd, tty.TCSANOW, new)
            tty.setraw(sys.stdout.fileno())
        c = connection.SSHSessionClient()
        c.dataReceived = self.write
        stdio.StandardIO(c)
        term = os.environ['TERM']
        if options['subsystem']:
            self.conn.sendRequest(self, 'subsystem', \
                common.NS(options['command']))
        elif options['command']:
            self.conn.sendRequest(self, 'exec', \
                common.NS(options['command']))
        else:
            winsz = fcntl.ioctl(fd, tty.TIOCGWINSZ, '12345678')
            rows, columns, xpixels, ypixels = struct.unpack('4H', winsz)
            self.conn.sendRequest(self, 'pty-req', common.NS(term) + \
                struct.pack('>4L', columns, rows, xpixels, ypixels) + \
                common.NS(''))
            self.conn.sendRequest(self, 'shell', '')

    def dataReceived(self, data):
        sys.stdout.write(data)
        sys.stdout.flush()
        #sys.stdout.flush()

    def extReceived(self, t, data):
        if t==connection.EXTENDED_DATA_STDERR:
            sys.stderr.write(data)
            sys.stderr.flush()

    def eofReceived(self):
        sys.stdin.close()

    def closed(self):
        if len(self.conn.channels) == 1: # just us left
            reactor.stop()

    def request_exit_status(self, data):
        global exitStatus
        exitStatus = struct.unpack('>L', data)[0]

# Make it script-callable for testing purposes
if __name__ == "__main__":
    run()
