from twisted.cred import portal
import pwd

class UnixSSHRealm:
    __implements__ = portal.IRealm

    def requestAvatar(self, username, mind, *interfaces):
        return interfaces[0], UnixSSHUser(username), lambda: None

class ISSHUser:
    """A user for an SSH service.  This lets the server get access to things
    like the users uid/gid, their home directory, and their shell.
    """

    def getUserGroupId(self):
        """
        @return: a tuple of (uid, gid) for the user.
        """

    def getHomeDir(self):
        """
        @return: a string containing the path of home directory.
        """

    def getShell(self):
        """
        @return: a string containing the path to the users shell.
        """

class UnixSSHUser:
    __implements__ = ISSHUser

    def __init__(self, username):
        self.username = username
        self.pwdData = pwd.getpwnam(self.username)

    def getUserGroupId(self):
        return self.pwdData[2:4]

    def getHomeDir(self):
        return self.pwdData[5]

    def getShell(self):
        return self.pwdData[6]
