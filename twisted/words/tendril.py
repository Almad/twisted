
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

from twisted.internet import passport
from twisted.persisted import styles
from twisted.protocols import irc
from twisted.python import log
from twisted.words import service

wordsService = service
del service

import string
import sys
import traceback

_LOGALL = 1

class ProxiedParticipant(wordsService.WordsClientInterface,
                         styles.Ephemeral):
    """I'm the client of a participant who is connected through Tendril.
    """

    nickname = None
    tendril = None

    def __init__(self, tendril, nickname):
        self.tendril = tendril
        self.nickname = nickname

    def setNick(self, nickname):
        self.nickname = nickname

    def receiveDirectMessage(self, sender, message):
        """Pass this message through tendril to my IRC counterpart.
        """
        self.tendril.msgFromWords(self.nickname,
                                  sender, message)

    # XXX: Do I need to do anything to ensure that I will do 'detatched'
    # when pickled?


class TendrilClient(irc.IRCClient, wordsService.WordsClientInterface):
    """I connect to the IRC server and broker traffic.

    TODO (and many of these belong in irc.IRCClient):
     * Login for IRCnets which require a PASS
     * Joining keyed channels.
     * NickServ cooperation.
    """

    networkSuffix = '@opn'
    nickname = 'tl'
    groupList = ['tendril_test']

    participants = None

    errorGroup = 'TendrilErrors'
    perspectiveName = nickname + networkSuffix

    realname = 'Tendril'
    versionName = 'Tendril'
    versionNum = '$Revision: 1.3 $'
    versionEnv = 'Twisted'

    helptext = (
        "Hi, I'm a Tendril bridge between here and %(service)s.",
        "You can send a private message to someone like this:",
        "/msg %(myNick)s msg theirNick Hi there!",
        )

    def __init__(self, service, groupList=None,
                 nickname=None, networkSuffix=None, perspectiveName=None):
        """Create a new Tendril client.

        service -- a twisted.words.service.Service, or at least
        something with a 'serviceName' attribute and 'addParticipant'
        and 'getPerspectiveNamed' methods which work like a
        words..Service.

        groupList -- a list of strings naming groups on the Words
        service to join and bridge to their counterparts on the IRC
        server.

        nickname -- a string to use as my nickname on the IRC network.

        networkSuffix -- a string to append to the nickname of the
        Participants I bring in through IRC, e.g. \"@opn\".

        perspectiveName -- the name of my perspective with this
        service.  Defaults to nickname + networkSuffix.

        To connect me to an IRC server, pass me as the 'protocol' when
        constructing a tcp.Client.
        """
        self.participants = {}
        self.dcc_sessions = {}

        if nickname:
            self.nickname = nickname
        if networkSuffix:
            self.networkSuffix = networkSuffix

        if not perspectiveName:
            perspectiveName = self.nickname + self.networkSuffix

        self.perspectiveName = perspectiveName

        if groupList:
            self.groupList = list(groupList)
        else:
            self.groupList = list(TendrilClient.groupList)

        self.service = service
        self.realname = 'Tendril to %s' % (service.serviceName,)

        self.attachToWords()

        self.perspective.joinGroup(self.errorGroup)

        for group in self.groupList:
            self.perspective.joinGroup(group)


    def attachToWords(self):
        try:
            self.perspective = (
                self.service.getPerspectiveNamed(self.perspectiveName))
        except wordsService.UserNonexistantError:
            self.perspective = (
                self.service.addParticipant(self.perspectiveName))
            if not self.perspective:
                raise RuntimeError, ("service %s won't give me my "
                                     "perspective named %s"
                                     % (self.service,
                                        self.perspectiveName))

        if self.perspective.client is self:
            log.msg("I seem to be already attached.")
            return

        try:
            self.perspective.attached(self, None)
        except passport.Unauthorized:
            if self.perspective.client:
                log.msg("%s is attached to my perspective: "
                        "kicking it off." % (self.perspective.client,))
                self.perspective.detached(self.perspective.client, None)
                self.perspective.attached(self, None)
            else:
                raise

    def signedOn(self):
        self.log("Welcomed by IRC server.", 'info')
        for group in self.groupList:
            self.join(groupToChannelName(group))

    def connectionLost(self):
        self.log("%s: Connection lost." % (self.transport,), 'info')
        for nick in self.participants.keys()[:]:
            self.logoutParticipant(nick)

    def lineReceived(self, line):
        if _LOGALL:
            self.log(line, 'dump')

        try:
            irc.IRCClient.lineReceived(self, line)
        except:
            s = apply(traceback.format_exception, sys.exc_info())
            s.append("The offending input line was:\n%s" % (line,))
            s = string.join(s,'')
            self.log(s, 'ERROR')

    def __getstate__(self):
        dct = self.__dict__.copy()
        # Don't save my imaginary friends.
        dct["participants"] = {}
        return dct

    def privmsg(self, user, channel, message):
        nick = string.split(user,'!')[0]
        if nick == self.nickname:
            return

        if string.lower(channel) == string.lower(self.nickname):
            parts = string.split(message, ' ', 1)
            cmd = parts[0]
            if len(parts) > 1:
                remainder = parts[1]
            else:
                remainder = None

            method = getattr(self, "bot_%s" % cmd, None)
            if method is not None:
                method(user, remainder)
            else:
                self.botUnknown(user, channel, message)
        else:
            # The message isn't to me, so it must be to a group.
            group = channelToGroupName(channel)
            try:
                self.getParticipant(nick).groupMessage(group, message)
            except wordsService.NotInGroupError:
                self.getParticipant(nick).joinGroup(group)
                self.getParticipant(nick).groupMessage(group, message)

    def noticed(self, user, channel, message):
        nick = string.split(user,'!')[0]
        if nick == self.nickname:
            return

        if string.lower(channel) == string.lower(self.nickname):
            # A private notice is most likely an auto-response
            # from something else, or a message from an IRC service.
            # Don't treat at as a command.
            pass
        else:
            # The message isn't to me, so it must be to a group.
            group = channelToGroupName(channel)
            try:
                self.getParticipant(nick).groupMessage(group, message)
            except wordsService.NotInGroupError:
                self.getParticipant(nick).joinGroup(group)
                self.getParticipant(nick).groupMessage(group, message)

    def action(self, user, channel, message):
        # XXX: Words needs 'emote' or something.
        group = channelToGroupName(channel)
        nick = string.split(user,'!',1)[0]
        self.perspective.groupMessage(group, '* %s%s %s' %
                                      (nick, self.networkSuffix, message))

    def bot_msg(self, sender, params):
        (nick, message) = string.split(params, ' ', 1)
        sender = string.split(sender, '!', 1)[0]
        try:
            self.getParticipant(sender).directMessage(nick, message)
        except wordsService.WordsError, e:
            self.notice(sender, "msg to %s failed: %s" % (nick, e))

    def bot_help(self, user, params):
        nick = string.split(user, '!', 1)[0]
        for l in self.helptext:
            self.notice(nick, l % {
                'myNick': self.nickname,
                'service': self.service.serviceName,
                })

    def botUnknown(self, user, channel, message):
        parts = string.split(message, ' ', 1)
        cmd = parts[0]
        if len(parts) > 1:
            remainder = parts[1]
        else:
            remainder = None

        if remainder is not None:
            # Default action is to try anything as a 'msg'
            # make sure the message is from a user and not a server.
            if ('!' in user) and ('@' in user):
                self.bot_msg(user, message)
        else:
            # But if the msg would be empty, don't that.
            # Just act confused.
            nick = string.split(user, '!', 1)[0]
            self.notice(nick, "I don't know what to do with '%s'.  "
                        "`/msg %s help` for help."
                        % (cmd, self.nickname))

    def irc_JOIN(self, prefix, params):
        nick = string.split(prefix,'!')[0]
        if nick == self.nickname:
            return
        channel = params[0]
        self.getParticipant(nick).joinGroup(channelToGroupName(channel))

    def irc_NICK(self, prefix, params):
        """When an IRC user changes their nickname

        this does *not* change the name of their perspectivee, just my
        nickname->perspective and client->nickname mappings.
        """
        old_nick = string.split(prefix,'!')[0]
        new_nick = params[0]
        if old_nick == self.nickname:
            self.nickname = new_nick
        else:
            self.changeParticipantNick(old_nick, new_nick)

    def irc_PART(self, prefix, params):
        nick = string.split(prefix,'!')[0]
        if nick == self.nickname:
            return
        channel = params[0]

        self.getParticipant(nick).leaveGroup(channelToGroupName(channel))

        if not self.getParticipant(nick).groups:
            self.logoutParticipant(nick)

    def irc_QUIT(self, prefix, params):
        nick = string.split(prefix,'!')[0]
        if nick == self.nickname:
            return
        self.logoutParticipant(nick)

    def irc_KICK(self, prefix, params):
        nick = string.split(prefix,'!')[0]
        channel = params[0]
        kicked = params[1]
        if string.lower(kicked) == string.lower(self.nickname):
            # Yikes!
            self.log("I've been kicked from %s: %s %s"
                     % (channel, prefix, params), 'NOTICE')
        else:
            group = channelToGroupName(channel)
            self.getParticipant(nick).leaveGroup(group)

    def irc_INVITE(self, prefix, params):
        group = channelToGroupName(params[1])
        if group in self.groupList:
            self.log("I'm accepting the invitation to join %s from %s."
                     % (group, prefix), 'NOTICE')
            self.join(groupToChannelName(group))

    def irc_ERR_BANNEDFROMCHAN(self, prefix, params):
        self.log("Join failed: %s %s" % (prefix, params), 'NOTICE')

    irc_ERR_CHANNELISFULL = \
                          irc_ERR_UNAVAILRESOURCE = \
                          irc_ERR_INVITEONLYCHAN =\
                          irc_ERR_NOSUCHCHANNEL = \
                          irc_ERR_BADCHANNELKEY = irc_ERR_BANNEDFROMCHAN

    def irc_ERR_NOTREGISTERED(self, prefix, params):
        self.log("Got ERR_NOTREGISTERED, re-running connectionMade().",
                 'NOTICE')
        self.connectionMade()

    def ctcpQuery_DCC(self, user, channel, data):
        nick = string.split(user,"!")[0]

        # We're pretty lenient about what we pass on, but the existance
        # of at least four parameters (type, arg, host, port) is really
        # required.
        if len(string.split(data)) < 4:
            self.ctcpMakeReply(nick, [('ERRMSG',
                                       'DCC %s :Malformed DCC request.'
                                       % (data))])
            return

        dcc_text = irc.dccDescribe(data)

        self.notice(nick, "Got your DCC %s"
                    % (irc.dccDescribe(data),))

        pName = self.getParticipant(nick).name
        self.dcc_sessions[pName] = (user, dcc_text, data)

        self.notice(nick, "If I should pass it on to another user, "
                    "/msg %s DCC PASSTO theirNick" % (self.nickname,))

    def bot_DCC(self, user, params):
        nick = string.split(user,"!")[0]
        pName = self.getParticipant(nick).name

        params = string.split(params)
        if len(params) <= 1:
            pass
        else:
            (cmd, dst) = params[:2]
            cmd = string.upper(cmd)
            if cmd == 'PASSTO':
                if self.dcc_sessions.has_key(pName):
                    (origUser,dcc_text,orig_data)=self.dcc_sessions[pName]
                    if dcc_text:
                        dcc_text = " for " + dcc_text
                    else:
                        dcc_text = ''

                    ctcpMsg = irc.ctcpStringify([('DCC',orig_data)])
                    try:
                        self.getParticipant(nick).directMessage(dst,
                                                                ctcpMsg)
                    except wordsService.WordsError, e:
                        self.notice(nick, "DCC offer to %s failed: %s"
                                    % (dst, e))
                    else:
                        self.notice(nick, "DCC offer%s extended to %s."
                                    % (dcc_text, dst))
                        del self.dcc_sessions[pName]

                else:
                    self.notice(nick, "I don't have an active DCC"
                                " handshake from you.")
                return

            elif cmd == "FORGET":
                if self.dcc_sessions.has_key(pName):
                    del self.dcc_sessions[pName]
                self.notice(nick, "I have now forgotten any DCC offers"
                            " from you.")
                return

        # endif len > 1
        pass

    # Words.Group --> IRC

    def sendLine(self, line):
        if (not self.transport) or (not self.transport.connected):
            return
        if _LOGALL:
            self.log(line, 'dump')
        irc.IRCClient.sendLine(self, line)

    def memberJoined(self, member, group):
        if self.isThisMine(member):
            return
        self.say(groupToChannelName(group), "%s joined." % (member,))

    def memberLeft(self, member, group):
        if self.isThisMine(member):
            return
        self.say(groupToChannelName(group), "%s left." % (member,))

    def receiveGroupMessage(self, sender, group, message):
        if not (group == self.errorGroup):
            if not self.isThisMine(sender):
                self.say(groupToChannelName(group),
                         "<%s> %s" % (sender, message))
        else:
            # A message in our errorGroup.
            if message == "participants":
                s = map(lambda i: str(i[0]), self.participants.values())
                s = string.join(s, ", ")
            elif message == "groups":
                s = map(str, self.perspective.groups)
                s = string.join(s, ", ")
            elif message == "transport":
                s = "%s connected: %s" % (self.transport,
                                          getattr(self.transport,
                                                  "connected"))
            else:
                return
            self.perspective.groupMessage(group, s)

    # Words.Participant --> IRC
    def msgFromWords(self, toNick, sender, message):
        if message[0] == irc.X_DELIM:
            # If there is a CTCP delimeter at the beginning of the
            # message, let's leave it there to accomidate not-so-
            # tolerant clients.
            dcc_data = None
            if message[1:5] == 'DCC ':
                dcc_query = irc.ctcpExtract(message)['extended'][0]
                dcc_data = dcc_query[1]

            if dcc_data:
                desc = "DCC " + irc.dccDescribe(dcc_data)
            else:
                desc = "CTCP request"

            self.msg(toNick, 'The following %s is from %s'
                     % (desc, sender))
            self.msg(toNick, '%s' % (message,))
        else:
            self.msg(toNick, '<%s> %s' % (sender, message))

    # IRC Participant Management
    def getParticipant(self, nick):
        """Get a Perspective (words.service.Participant) for a IRC user.

        And if I don't have one around, I'll make one.
        """
        if not self.participants.has_key(nick):
            self.newParticipant(nick)

        return self.participants[nick][0]

    def getClient(self, nick):
        if not self.participants.has_key(nick):
            self.newParticipant(nick)
        return self.participants[nick][1]

    # TODO: let IRC users authorize themselves and then give them a
    # *real* perspective (one attached to their identity) instead
    # of one of my @networkSuffix-Nobody perspectives.

    def newParticipant(self, nick):
        try:
            p = self.service.getPerspectiveNamed(nick +
                                                 self.networkSuffix)
        except wordsService.UserNonexistantError:
            p = self.service.addParticipant(nick + self.networkSuffix)
            if not p:
                raise wordsService.wordsError("Eeek!  Couldn't get OR "
                                              "make a perspective for "
                                              "'%s%s'." %
                                              (nick, self.networkSuffix))

        c = ProxiedParticipant(self, nick)
        p.attached(c, None)

        self.participants[nick] = [p, c]

    def changeParticipantNick(self, old_nick, new_nick):
        if not self.participants.has_key(old_nick):
            return

        (p, c) = self.participants[old_nick]
        c.setNick(new_nick)

        self.participants[new_nick] = self.participants[old_nick]
        del self.participants[old_nick]

    def logoutParticipant(self, nick):
        if not self.participants.has_key(nick):
            return

        (p, c) = self.participants[nick]
        p.detached(c, None)
        c.tendril = None
        del self.participants[nick]

    def isThisMine(self, sender):
        """Returns true if 'sender' is the name of a perspective I'm providing.
        """
        if self.perspectiveName == sender:
            return "That's ME!"

        for (p, c) in self.participants.values():
            if p.name == sender:
                return 1
        return 0

    def log(self, message, priority=None):
        """I need to give Twisted a prioritized logging facility one of these days.
        """
        log.msg(message)
        if priority in ('info', 'NOTICE', 'ERROR'):
            self.perspective.groupMessage(self.errorGroup, message)


def channelToGroupName(channelName):
    """Map an IRC channel name to a Words group name.

    IRC is case-insensitive, words is not.  Arbitrtarily decree that all
    IRC channels should be lowercase.

    Warning: This prevents me from relaying text from IRC to
    a mixed-case Words group.  That is, any words group I'm
    in should have an all-lowercase name.
    """

    # Normalize case and trim leading '#'
    groupName = string.lower(channelName[1:])
    return groupName

def groupToChannelName(groupName):
    # Don't add a "#" here, because we do so in the outgoing IRC methods.
    channelName = groupName
    return channelName
