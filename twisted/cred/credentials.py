# -*- test-case-name: twisted.test.test_newcred-*-
from twisted.python import components

class ICredentials(components.Interface):
    """I check credentials.

    @cvar __implements__: Implementors _must_ provide an __implements__
    attribute which contains at least the list of sub-interfaces of
    ICredentials to which it conforms.
    """


class IUsernamePassword(ICredentials):
    """I encapsulate a username and password.

    @ivar username: What do you think?
    """

    def checkPassword(self, password):
        """
        @return: a deferred which becomes, or a boolean indicating if the
        password matches.
        """

class IAnonymous(ICredentials):
    """I am an explicitly anonymous request for access.
    """

class SimpleMD5ChallengeResponse(ICredentials):
    """XXX specify PB c/r protocol
    """

class UsernamePassword:
    __implements__ = IUsernamePassword
    def __init__(self, username, password):
        self.username = username
        self.password = password

    def checkPassword(self, password):
        return self.password == password

class Anonymous:
    __implements__ = IAnonymous
