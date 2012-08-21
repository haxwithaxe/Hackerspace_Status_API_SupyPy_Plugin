###
# Copyright: Public Domain
###

import json
import new
import os
import re
import time
import urllib2
import socket
import sgmllib
import threading

import supybot.conf as conf
import supybot.utils as utils
import supybot.world as world
from supybot.commands import *
import supybot.ircutils as ircutils
import supybot.registry as registry
import supybot.callbacks as callbacks

class status(object):
    def __call__(self):
        self.__init__(self)
    def __init__(self):
        self.urlre = re.compile('http[s]?[:]//.+\..+')
    def get(self, src):
        if self.urlre.match(src):
            result = self.download(src)
        else:
            result = self.read(src)
        return json.loads(result)

    def download(self, src):
        try:
            result = urllib2.urlopen(src).read()
        except urllib2.URLError as urlerr:
            result = '{"default":"url not found"}'
        return result

    def read(self,src):
        if os.path.exists(src):
            file_obj = open(src,'r')
            result = file_obj.read()
            file_obj.close()
        else:
            result = '{"default":"file not found"}'
        return result


def get_status_name(irc, msg, args, state):
    if not registry.isValidRegistryName(args[0]):
        state.errorInvalid('status name', args[0],
                           'Status names must not include spaces.')
    state.args.append(callbacks.canonicalName(args.pop(0)))
addConverter('status_name', get_status_name)

def get_status_uri(irc, msg, args, state):
    if not utils.web.urlRe.match(args[0]) and not os.exists(args[0]):
        state.errorInvalid('status uri', args[0],
                           'Status URIs must be valid URLs or file names.')
    state.args.append(callbacks.canonicalName(args.pop(0)))
addConverter('status_uri', get_status_uri)

class HackerspaceStatus(callbacks.Plugin):
    """This plugin is useful both for announcing updates to HackerspaceStatus feeds in a
    channel, and for retrieving the headlines of HackerspaceStatus feeds via command.  Use
    the "add" command to add feeds to this plugin, and use the "announce"
    command to determine what feeds should be announced in a given channel."""
    threaded = True
    def __init__(self, irc):
        self.__parent = super(HackerspaceStatus, self)
        self.__parent.__init__(irc)
        # Schema is space : [src, command]
        self.hackerspace_names = callbacks.CanonicalNameDict()
        self.locks = {}
        self.lastRequest = {}
        self.cachedStatus = {}
        self.gettingLockLock = threading.Lock()
        for space in self.registryValue('hackerspace_status'):
            try:
                src = self.registryValue(registry.join(['hackerspace_status', space]))
            except registry.NonExistentRegistryEntry:
                self.log.warning('%s is not registered.',space)
                continue
            self.makeStatusCommand(space, src)
            self.getStatus(src) # So announced feeds don't announce on startup.

    def isCommandMethod(self, name):
        if not self.__parent.isCommandMethod(name):
            if name in self.hackerspace_names:
                return True
            else:
                return False
        else:
            return True

    def listCommands(self):
        return self.__parent.listCommands(self.hackerspace_names.keys())

    def getCommandMethod(self, command):
        try:
            return self.__parent.getCommandMethod(command)
        except AttributeError:
            return self.hackerspace_names[command[0]][1]

    def _registerStatus(self, name, src=''):
        self.registryValue('hackerspace_status').add(name)
        group = self.registryValue('hackerspace_status', value=False)
        conf.registerGlobalValue(group, name, registry.String(src, ''))

    def __call__(self, irc, msg):
        self.__parent.__call__(irc, msg)
        irc = callbacks.SimpleProxy(irc, msg)
        newStatus = {}
        for channel in irc.state.channels:
            status = self.registryValue('announce', channel)
            for name in status:
                commandName = callbacks.canonicalName(name)
                if self.isCommandMethod(commandName):
                    src = self.hackerspace_names[commandName][0]
                else:
                    src = name
                if self.willGetStatusUpdate(src):
                    newStatus.setdefault((src, name), []).append(channel)
        for ((src, name), channels) in newStatus.iteritems():
            # We check if we can acquire the lock right here because if we
            # don't, we'll possibly end up spawning a lot of threads to get
            # the feed, because this thread may run for a number of bytecodes
            # before it switches to a thread that'll get the lock in
            # _newHeadlines.
            if self.acquireLock(src, blocking=False):
                try:
                    t = threading.Thread(target=self._statusChanges,
                                         name=format('%u', src),
                                         args=(irc, channels, name, src))
                    self.log.info('Checking for announcements at %u', src)
                    world.threadsSpawned += 1
                    t.setDaemon(True)
                    t.start()
                finally:
                    self.releaseLock(src)
                    time.sleep(0.1) # So other threads can run.

    def buildStatus(self, status, channel, msg_format='default'):
        status_changes = []
        status_changes = [format('%s', s[msg_format]) for s in status]
        return status_changes

    def _statusChanges(self, irc, channels, name, src):
        try:
            # We acquire the lock here so there's only one announcement thread
            # in this code at any given time.  Otherwise, several announcement
            # threads will getStatus (all blocking, in turn); then they'll all
            # want to send their news messages to the appropriate channels.
            # Note that we're allowed to acquire this lock twice within the
            # same thread because it's an RLock and not just a normal Lock.
            self.acquireLock(src)
            try:
                oldresults = self.cachedStatus[src]
                old_status = self.getStatusMsgs(oldresults)
            except KeyError:
                old_status = []
            newresults = self.getStatus(src)
            status_changes = self.getStatus(newresults)
            if len(status_changes) == 1:
                s = status_changes[0][0]
                if s in ('Timeout getting status.',
                         'Unable to get status.'):
                    self.log.debug('%s %u', s, src)
                    return
            status = self.buildStatus(status_changes, channel)
            irc.replies(status, prefixer=pre, joiner=sep,
                        to=channel, prefixNick=False, private=True)
        finally:
            self.releaseLock(src)

    def willGetStatusUpdate(self, src):
        now = time.time()
        wait = self.registryValue('waitPeriod')
        if src not in self.lastRequest or now - self.lastRequest[src] > wait:
            return True
        else:
            return False

    def acquireLock(self, src, blocking=True):
        try:
            self.gettingLockLock.acquire()
            try:
                lock = self.locks[src]
            except KeyError:
                lock = threading.RLock()
                self.locks[src] = lock
            return lock.acquire(blocking=blocking)
        finally:
            self.gettingLockLock.release()

    def releaseLock(self, src):
        self.locks[src].release()

    def getStatus(self, src=''):
        def error(s):
            return {'default':'not found'}
        try:
            # This is the most obvious place to acquire the lock, because a
            # malicious user could conceivably flood the bot with commands
            # and DoS the website in question.
            self.acquireLock(src)
            if self.willGetStatusUpdate(src):
                results = status().get(src)
                if results and (src not in self.cachedStatus or results !=
                        self.cachedStatus[src]):
                    self.cachedStatus[src] = results
                    self.lastRequest[src] = time.time()
                else:
                    self.log.debug('Not caching results.')
            try:
                return self.cachedStatus[src]
            except KeyError:
                wait = self.registryValue('waitPeriod')
                # If there's a problem retrieving the feed, we should back off
                # for a little bit before retrying so that there is time for
                # the error to be resolved.
                self.lastRequest[src] = time.time() - .5 * wait
                return error('Unable to get status.')
        finally:
            self.releaseLock(src)

    def add(self, irc, msg, args, space, src):
        """<hackerspace> <source>

        Adds a command to this plugin that will look up the status of the given hackerspace at the
        given location.
        """
        print('in add %s %s' % (space,src))
        self.makeStatusCommand(space, src)
        irc.replySuccess()
    add = wrap(add, ['text', 'text'])

    def remove(self, irc, msg, args, space):
        """<hackerspace>

        Removes the command for getting status of <hackerspace> from
        this plugin.
        """
        if space not in self.hackerspace_names:
            irc.error('There is no record for that hackerspace.')
            return
        del self.hackerspace_names[space]
        conf.supybot.plugins.HackerspaceStatus.hackerspace_status().remove(space)
        conf.supybot.plugins.HackerspaceStatus.unregister(space)
        irc.replySuccess()
    remove = wrap(remove, ['text'])

    def makeStatusCommand(self, space, src):
        docstring = format("""[<format>]

        Reports the status for %s at the HackerspaceStatus feed %u.  If
        <format> is given, returns that format.
        HackerspaceStatus feeds are only looked up every supybot.plugins.HackerspaceStatus.waitPeriod
        seconds, which defaults to 120 (2 minutes) since that's what we chose
        randomly.
        """, space, src)
        if src not in self.locks:
            self.locks[src] = threading.RLock()
        if self.isCommandMethod(space):
            s = format('I already have a record for a hackerspace named
                    %s.',space)
            raise callbacks.Error, s
        def f(self, irc, msg, args):
            args.insert(0, src)
            self.hss(irc, msg, args)
        f = utils.python.changeFunctionName(f, space, docstring)
        f = new.instancemethod(f, self, HackerspaceStatus)
        self.hackerspace_names[space] = (src, f)
        self._registerStatus(space, src)
 
    def hss(self, irc, msg, args, src, msg_format='default'):
        """<hackerspace> [<format>]

        Gets the status of the given hackerspace.
        If <format> is given, return that format if available.
        """
        self.log.debug('Fetching %u', src)
        status = self.getStatus(src)
        if irc.isChannel(msg.args[0]):
            channel = msg.args[0]
        else:
            channel = None
        try:
            status_msg = status[msg_format]
        except KeyError:
            status_msg = status['default']
        irc.reply(status_msg)
    hss = wrap(hss, ['text', additional('text')])

    class announce(callbacks.Commands):
        def list(self, irc, msg, args, channel):
            """[<channel>]

            Returns the list of feeds announced in <channel>.  <channel> is
            only necessary if the message isn't sent in the channel itself.
            """
            announce = conf.supybot.plugins.HackerspaceStatus.announce
            status = format('%L', list(announce.get(channel)()))
            irc.reply(status or 'I am currently not announcing any status changes.')
        list = wrap(list, ['channel',])

        def add(self, irc, msg, args, channel, status):
            """[<channel>] <name|url> [<name|url> ...]

            Adds the list of feeds to the current list of announced feeds in
            <channel>.  Valid feeds include the names of registered feeds as
            well as URLs for RSS feeds.  <channel> is only necessary if the
            message isn't sent in the channel itself.
            """
            announce = conf.supybot.plugins.HackerspaceStatus.announce
            S = announce.get(channel)()
            for stat in status:
                S.add(stat)
            announce.get(channel).setValue(S)
            irc.replySuccess()
        add = wrap(add, [('checkChannelCapability', 'op'),
                         many(first('status_uri', 'status_name'))])

        def remove(self, irc, msg, args, channel, status):
            """[<channel>] <name|url> [<name|url> ...]

            Removes the list of feeds from the current list of announced feeds
            in <channel>.  Valid feeds include the names of registered feeds as
            well as URLs for RSS feeds.  <channel> is only necessary if the
            message isn't sent in the channel itself.
            """
            announce = conf.supybot.plugins.HackerspaceStatus.announce
            S = announce.get(channel)()
            for stat in status:
                S.discard(stat)
            announce.get(channel).setValue(S)
            irc.replySuccess()
        remove = wrap(remove, [('checkChannelCapability', 'op'),
                               many(first('status_uri', 'status_name'))])

Class = HackerspaceStatus

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
