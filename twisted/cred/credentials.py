# -*- test-case-name: twisted.test.test_newcred-*-

# Twisted, the Framework of Your Internet
# Copyright (C) 2003 Matthew W. Lefkowitz
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

from twisted.python import components
from zope import interface

import hmac
import time
import random

class ICredentials(components.Interface):
    """I check credentials.

    Implementors _must_ specify which sub-interfaces of ICredentials
    to which it conforms, using zope.interface.implements().
    """


class IUsernameHashedPassword(ICredentials):
    """I encapsulate a username and a hashed password.

    This credential is used when a hashed password is received from the
    party requesting authentication.  CredentialCheckers which check this
    kind of credential must store the passwords in plaintext (or as
    password-equivalent hashes) form so that they can be hashed in a manner
    appropriate for the particular credentials class.

    @type username: C{str}
    @ivar username: The username associated with these credentials.
    """

    def checkPassword(self, password):
        """Validate these credentials against the correct password.

        @param password: The correct, plaintext password against which to
        check.

        @return: a deferred which becomes, or a boolean indicating if the
        password matches.
        """


class IUsernamePassword(ICredentials):
    """I encapsulate a username and a plaintext password.

    This encapsulates the case where the password received over the network
    has been hashed with the identity function (That is, not at all).  The
    CredentialsChecker may store the password in whatever format it desires,
    it need only transform the stored password in a similar way before
    performing the comparison.

    @type username: C{str}
    @ivar username: The username associated with these credentials.

    @type password: C{str}
    @ivar password: The password associated with these credentials.
    """

    def checkPassword(self, password):
        """Validate these credentials against the correct password.

        @param password: The correct, plaintext password against which to
        check.

        @return: a deferred which becomes, or a boolean indicating if the
        password matches.
        """


class IAnonymous(ICredentials):
    """I am an explicitly anonymous request for access.
    """


class CramMD5Credentials:
    interface.implements(IUsernameHashedPassword)

    challenge = ''
    response = ''

    def __init__(self, host=None):
        self.host = host

    def getChallenge(self):
        if self.challenge:
            return self.challenge
        # The data encoded in the first ready response contains an
        # presumptively arbitrary string of random digits, a timestamp, and
        # the fully-qualified primary host name of the server.  The syntax of
        # the unencoded form must correspond to that of an RFC 822 'msg-id'
        # [RFC822] as described in [POP3].
        #   -- RFC 2195
        r = random.randrange(0x7fffffff)
        t = time.time()
        self.challenge = '<%d.%d@%s>' % (r, t, self.host)
        return self.challenge

    def setResponse(self, response):
        self.username, self.response = response.split(None, 1)

    def moreChallenges(self):
        return False

    def checkPassword(self, password):
        verify = hmac.HMAC(password, self.challenge).hexdigest()
        return verify == self.response

components.backwardsCompatImplements(CramMD5Credentials)

class UsernameHashedPassword:
    interface.implements(IUsernameHashedPassword)

    def __init__(self, username, hashed):
        self.username = username
        self.hashed = hashed

    def checkPassword(self, password):
        return self.hashed == password

components.backwardsCompatImplements(UsernameHashedPassword)

class UsernamePassword:
    interface.implements(IUsernamePassword)

    def __init__(self, username, password):
        self.username = username
        self.password = password

    def checkPassword(self, password):
        return self.password == password

components.backwardsCompatImplements(UsernamePassword)

class Anonymous:
    interface.implements(IAnonymous)

components.backwardsCompatImplements(Anonymous)
