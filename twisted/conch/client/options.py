# Copyright (c) 2001-2004 Twisted Matrix Laboratories.
# See LICENSE for details.

#
from twisted.conch.ssh.transport import SSHClientTransport
from twisted.python import usage

import connect

import sys

class ConchOptions(usage.Options):

    optParameters = [['user', 'l', None, 'Log in using this user name.'],
                     ['identity', 'i', None],
                     ['ciphers', 'c', None],
                     ['macs', 'm', None],
                     ['connection-usage', 'K', None],
                     ['port', 'p', None, 'Connect to this port.  Server must be on the same port.'],
                     ['option', 'o', None, 'Ignored OpenSSH options'],
                     ['host-key-algorithms', '', None],
                     ['known-hosts', '', None, 'File to check for host keys'],
                     ['user-authentications', '', None, 'Types of user authentications to use.'],
                   ]

    optFlags = [['version', 'V', 'Display version number only.'],
                ['compress', 'C', 'Enable compression.'],
                ['log', 'v', 'Log to stderr'],
                ['nocache', 'I', 'Do not allow connection sharing over this connection.'],
                ['nox11', 'x', 'Disable X11 connection forwarding (default)'],
                ['agent', 'A', 'Enable authentication agent forwarding'],
                ['noagent', 'a', 'Disable authentication agent forwarding (default)'],
                ['reconnect', 'r', 'Reconnect to the server if the connection is lost.'],
               ]

    identitys = []
    conns = None

    def opt_identity(self, i):
        """Identity for public-key authentication"""
        self.identitys.append(i)

    def opt_ciphers(self, ciphers):
        "Select encryption algorithm"
        ciphers = ciphers.split(',')
        for cipher in ciphers:
            if cipher not in SSHClientTransport.supportedCiphers:
                sys.exit("Unknown cipher type '%s'" % cipher)
        self['ciphers'] = ciphers


    def opt_macs(self, macs):
        "Specify MAC algorithms"
        macs = macs.split(',')
        for mac in macs:
            if mac not in SSHClientTransport.supportedMACs:
                sys.exit("Unknown mac type '%s'" % mac)
        self['macs'] = macs

    def opt_host_key_algorithms(self, hkas):
        "Select host key algorithms"
        hkas = hkas.split(',')
        for hka in hkas:
            if hka not in SSHClientTransport.supportedPublicKeys:
                sys.exit("Unknown host key type '%s'" % hka)
        self['host-key-algorithms'] = hkas

    def opt_user_authentications(self, uas):
        "Choose how to authenticate to the remote server"
        self['user-authentications'] = uas.split(',')

    def opt_connection_usage(self, conns):
        conns = conns.split(',')
        connTypes = connect.connectTypes.keys()
        for conn in conns:
            if conn not in connTypes:
                sys.exit("Unknown connection type '%s'" % conn)
        self.conns = conns
        
#    def opt_compress(self):
#        "Enable compression"
#        self.enableCompression = 1
#        SSHClientTransport.supportedCompressions[0:1] = ['zlib']
