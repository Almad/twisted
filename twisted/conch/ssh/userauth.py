# Twisted, the Framework of Your Internet
# Copyright (C) 2001-2002 Matthew W. Lefkowitz
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

"""Implementation of the ssh-userauth service.  Currently implemented authentication types are public-key and password.

This module is unstable.

Maintainer: U{Paul Swartz<mailto:z3p@twistedmatrix.com>}
"""

import struct
from twisted.conch import error, credentials
from twisted.internet import app, defer, reactor
from twisted.python import failure, log
from common import NS, getNS, MP
import keys, transport, service

class SSHUserAuthServer(service.SSHService):
    name = 'ssh-userauth'
    loginTimeout = 10 * 60 * 60 # 10 minutes before we disconnect them
    attemptsBeforeDisconnect = 20 # number of attempts to allow before a disconnect
    protocolMessages = None # set later
    supportedMethods = ['publickey', 'password']

    def serviceStarted(self):
        self.supportedAuthentications = self.supportedMethods[:] 
        self.authenticatedWith = []
        self.loginAttempts = 0
        self.user = None
        self.nextService = None
        self.portal = self.transport.factory.portal

        if not self.transport.isEncrypted('out'):
            self.supportedAuthentications.remove('password')
            if 'keyboard-interactive' in self.supportedAuthentications:
                self.supportedAuthentications.remove('keyboard-interactive')
            # don't let us transport password in plaintext
        self.cancelLoginTimeout = reactor.callLater(self.loginTimeout, 
                                                    self.timeoutAuthentication)

    def serviceStopped(self):
        if self.cancelLoginTimeout:
            self.cancelLoginTimeout.cancel()
            self.cancelLoginTimeout = None

    def timeoutAuthentication(self):
        self.cancelLoginTimeout = None
        self.transport.sendDisconnect(
            transport.DISCONNECT_NO_MORE_AUTH_METHODS_AVAILABLE,
            'you took too long')


    def tryAuth(self, kind, user, data):
        log.msg('%s trying auth %s' % (user, kind))
        if kind not in self.supportedAuthentications:
            return defer.fail(error.ConchError('unsupported authentication, failing'))
        kind = kind.replace('-', '_')
        f = getattr(self,'auth_%s'%kind, None)
        if f:
            return f(data)
        return defer.fail(error.ConchError('bad auth type: %s' % kind))

    def ssh_USERAUTH_REQUEST(self, packet):
        user, nextService, method, rest = getNS(packet, 3)
        if user != self.user or nextService != self.nextService:
            self.authenticatedWith = [] # clear auth state
        self.user = user
        self.nextService = nextService
        self.method = method
        d = self.tryAuth(method, user, rest)
        d.addCallbacks(self._cbFinishedAuth)
        d.addErrback(self._ebMaybeBadAuth)
        d.addErrback(self._ebBadAuth)

    def _cbFinishedAuth(self, (interface, avatar, logout)):
        log.msg('%s authenticated with %s' % (self.user, self.method))
        self.transport.sendPacket(MSG_USERAUTH_SUCCESS, '')
        self.transport.authenticatedUser = avatar
        self.transport.logoutFunction = logout
        self.transport.setService(self.transport.factory.services[self.nextService]())

    def _ebMaybeBadAuth(self, reason):
        reason.trap(error.NotEnoughAuthentication)
        self.transport.sendPacket(MSG_USERAUTH_FAILURE, NS(','.join(self.supportedAuthentications))+'\xff')

    def _ebBadAuth(self, reason):
        if reason.type == error.IgnoreAuthentication:
            return 
        if self.method != 'none': 
            log.msg('%s failed auth %s' % (self.user, self.method))
            log.msg('reason:')
            if reason.type == error.ConchError:
                log.msg(str(reason))
            else:
                log.msg(reason.printTraceback())
            self.loginAttempts += 1
            if self.loginAttempts > self.attemptsBeforeDisconnect:
                self.transport.sendDisconnect(transport.DISCONNECT_NO_MORE_AUTH_METHODS_AVAILABLE,
                                              'too many bad auths')
        self.transport.sendPacket(MSG_USERAUTH_FAILURE, NS(','.join(self.supportedAuthentications))+'\x00')

    def auth_publickey(self, packet):
        hasSig = ord(packet[0])
        algName, blob, rest = getNS(packet[1:], 2)
        pubKey = keys.getPublicKeyObject(data = blob)
        b = NS(self.transport.sessionID) + chr(MSG_USERAUTH_REQUEST) + \
            NS(self.user) + NS(self.nextService) + NS('publickey') + \
            chr(hasSig) +  NS(keys.objectType(pubKey)) + NS(blob)
        signature = hasSig and getNS(rest)[0] or None
        c = credentials.SSHPrivateKey(self.user, blob, b, signature)
        if hasSig:
            return self.portal.login(c, None, None)
        else:
            return self.portal.login(c, None, None).addErrback(self._ebCheckKey,
                                                               packet[1:])

    def _ebCheckKey(self, reason, packet):
        reason.trap(error.ValidPublicKey)
        # if we make it here, it means that the publickey is valid
        self.transport.sendPacket(MSG_USERAUTH_PK_OK, packet)
        return failure.Failure(error.IgnoreAuthentication())

    def auth_password(self, packet):
        password = getNS(packet[1:])[0]
        c = credentials.UsernamePassword(self.user, password)
        return self.portal.login(c, None, None)

#    def auth_keyboard_interactive(self, ident, packet):
#        if packet != '':
#            self.transport.sendDisconnect(transport.DISCONNECT_PROTOCOL_ERROR, "keyboard_interactive auth takes no data")
#        if hasattr(self, '_pamDeferred'):
#            return defer.fail(error.ConchError('cannot run kbd-int twice at once'))
#        d = pamauth.pamAuthenticate('ssh', ident.name, self._pamConv)
#        return d
#
#    def _pamConv(self, items):
#        resp = []
#        for message, kind in items:
#            if kind == 1: # password
#                resp.append((message, 0))
#            elif kind == 2: # text
#                resp.append((message, 1))
#            elif kind in (3, 4):
#                return defer.fail(error.ConchError('cannot handle PAM 3 or 4 messages'))
#            else:
#                return defer.fail(error.ConchError('bad PAM auth kind %i' % kind))
#        packet = NS('')+NS('')+NS('')
#        packet += struct.pack('>L', len(resp))
#        for prompt, echo in resp:
#            packet += NS(prompt)
#            packet += chr(echo)
#        self.transport.sendPacket(MSG_USERAUTH_INFO_REQUEST, packet)
#        self._pamDeferred = defer.Deferred()
#        return self._pamDeferred
#
#    def ssh_USERAUTH_INFO_RESPONSE(self, packet):
#        if not self.identity:
#            return defer.fail(error.ConchError('bad username'))
#        d = self._pamDeferred
#        del self._pamDeferred
#        try:
#            resp = []
#            numResps = struct.unpack('>L', packet[:4])[0]
#            packet = packet[4:]
#            while packet:
#                response, packet = getNS(packet)
#                resp.append((response, 0))
#            assert len(resp) == numResps
#        except:
#            d.errback(failure.Failure())
#        else:
#            d.callback(resp)
#            

    # overwrite on the client side            
    def areDone(self):
        return len(self.authenticatedWith)>0
        

class SSHUserAuthClient(service.SSHService):
    name = 'ssh-userauth'
    protocolMessages = None # set later
    def __init__(self, user, instance):
        self.user = user
        self.instance = instance
        self.authenticatedWith = []
        self.triedPublicKeys = []

    def serviceStarted(self):
        self.askForAuth('none', '')

    def askForAuth(self, kind, extraData):
        self.lastAuth = kind
        self.transport.sendPacket(MSG_USERAUTH_REQUEST, NS(self.user) + \
                                  NS(self.instance.name) + NS(kind) + extraData)
    def tryAuth(self, kind):
        f= getattr(self,'auth_%s'%kind, None)
        if f:
            return f()
        
    def ssh_USERAUTH_SUCCESS(self, packet):
        self.transport.setService(self.instance)
        self.ssh_USERAUTH_SUCCESS = lambda *a: None # ignore these

    def ssh_USERAUTH_FAILURE(self, packet):
        canContinue, partial = getNS(packet)
        canContinue = canContinue.split(',')
        partial = ord(partial)
        if partial:
            self.authenticatedWith.append(self.lastAuth)
        for method in canContinue:
            if method not in self.authenticatedWith and self.tryAuth(method):
                return 
        self.transport.sendDisconnect(transport.DISCONNECT_NO_MORE_AUTH_METHODS_AVAILABLE, 'no more authentication methods available')

    def ssh_USERAUTH_PK_OK(self, packet):
        if self.lastAuth == 'publickey':
            # this is ok
            d  = self.getPrivateKey()
            if not d:
                self.askForAuth('none', '')
                # this will fail, we'll move on
                return
            d.addCallback(self._cbPK_OK)
            d.addErrback(self._ebPK_OK)
        elif self.lastAuth == 'password':
            prompt, language, rest = getNS(packet, 2)
            self._oldPass = self._newPass = None
            self.getPassword('Old Password: ').addCallbacks(self._setOldPass, self._errPass)
            self.getPassword(prompt).addCallbacks(self._setNewPass, self._errPass)
        elif self.lastAuth == 'keyboard-interactive':
            # can't handle this in the client, so just try something else
            self.askForAuth('none', '')
            #return self.ssh_USERAUTH_INFO_RESPONSE(packet)

    def _cbPK_OK(self, privateKey):
        publicKey = self.lastPublicKey
        keyType =  keys.objectType(privateKey)
        b = NS(self.transport.sessionID) + chr(MSG_USERAUTH_REQUEST) + \
            NS(self.user) + NS(self.instance.name) + NS('publickey') + '\xff' + \
            NS(keyType) + NS(publicKey)
        self.askForAuth('publickey', '\xff' + NS(keyType) + NS(publicKey) + \
                        NS(keys.signData(privateKey, b)))

    def _ebPK_OK(self, ignored):
        self.askForAuth('none', '')

    def _setOldPass(self, op):
        if self._newPass:
            np = self._newPass
            self._newPass = None
            self.askForAuth('password', '\xff'+NS(op)+NS(np))
        else:
            self._oldPass = op

    def _setNewPass(self, np):
        if self._oldPass:
            op = self._oldPass
            self._oldPass = None
            self.askForAuth('password', '\xff'+NS(op)+NS(np))
        else:
            self._newPass = np

    def _errPass(self, reason):
        self.askForAuth('none', '')

    def auth_publickey(self):
        publicKey = self.getPublicKey()
        if publicKey:
            self.lastPublicKey = publicKey
            self.triedPublicKeys.append(publicKey)
            keyType = getNS(publicKey)[0]
            log.msg('using key of type %s' % keyType)
            self.askForAuth('publickey', '\x00' + NS(keyType) + \
                            NS(publicKey))
            return 1
        else:
            return 0

    def auth_password(self):
        d = self.getPassword()
        if d:
            d.addCallbacks(self._cbPassword, self._errPass)
            return 1
        else: # returned None, don't do password auth
            return 0

    def _cbPassword(self, password):
        self.askForAuth('password', '\x00'+NS(password))

    def getPublicKey(self):
        """
        Return a public key for the user.  If no more public keys are
        available, return None.

        @rtype: C{str}/C{None}
        """
        raise NotImplementedError

    def getPrivateKey(self):
        """
        Return a C{Deferred} that will be called back with the private key
        corresponding to the last public key from getPublicKey().
        If the private key is not available, errback on the Deferred.

        @rtype: C{Deferred}
        """
        raise NotImplementedError

    def getPassword(self, prompt = None):
        """
        Return a C{Deferred} that will be called back with a password.
        prompt is a string to display for the password, or None for a generic
        'user@hostname's password: '.

        @type prompt: C{str}/C{None}
        @rtype: C{Deferred}
        """
        raise NotImplementedError

MSG_USERAUTH_REQUEST          = 50
MSG_USERAUTH_FAILURE          = 51
MSG_USERAUTH_SUCCESS          = 52
MSG_USERAUTH_BANNER           = 53
MSG_USERAUTH_PASSWD_CHANGEREQ = 60
MSG_USERAUTH_INFO_REQUEST     = 60
MSG_USERAUTH_INFO_RESPONSE    = 61
MSG_USERAUTH_PK_OK            = 60

messages = {}
import userauth
for v in dir(userauth):
    if v[:4]=='MSG_':
        messages[getattr(userauth,v)] = v # doesn't handle doubles

SSHUserAuthServer.protocolMessages = messages
SSHUserAuthClient.protocolMessages = messages

try:
    import pamauth
except:
    pass
else:
    SSHUserAuthServer.supportedMethods.append('keyboard-interactive')
