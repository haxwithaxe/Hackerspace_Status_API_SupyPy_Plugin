###
# Copyright: Public Domain
###

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
    def __init__(self):
        self.urlre = re.compile('http[s]?[:]//.+\..+')
    def get(self,src):
        if self.urlre.match(src):
            result = self.download(src)
        else:
            result = self.read(src)
        return json.loads(result)

    def download(self,src):
        try:
            result = urllib2.urlopen(src).read()
        except urllib2.URLError as urlerr:
            result = '{"default":"url not found"}'
        return result

    def read(self,src):
        if os.exists(src):
            file_obj = open(src,'r')
            result = file_obj.read()
            file_obj.close()
        else:
            result = '{"default":"file not found"}'
        return result

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
        self.makeStatusCommand(name, msg_format)
        self.getFeed() # So announced feeds don't announce on startup.

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
                    src = self.statusNames[commandName][0]
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
                                         name=format('Fetching %u', src),
                                         args=(irc, channels, name, src))
                    self.log.info('Checking for announcements at %u', src)
                    world.threadsSpawned += 1
                    t.setDaemon(True)
                    t.start()
                finally:
                    self.releaseLock(src)
                    time.sleep(0.1) # So other threads can run.

    def buildHeadlines(self, status, channel, config='announce.showLinks'):
        status_changes = []
        if self.registryValue(config, channel):
            for stat in status:
                if stat[1]:
                    status_changes.append(format('%s %u',
                                        stat[0],
                                        stat[1].encode('utf-8')))
                else:
                    status_changes.append(format('%s', stat[0]))
        else:
            for stat in status:
                status_changes = [format('%s', s[0]) for s in status]
        return status_changes

    def _statusChanges(self, irc, channels, name, src):
        try:
            # We acquire the lock here so there's only one announcement thread
            # in this code at any given time.  Otherwise, several announcement
            # threads will getFeed (all blocking, in turn); then they'll all
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
                if s in ('Timeout downloading feed.',
                         'Unable to download feed.'):
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

    def getStatus(self, src):
        def error(s):
            return {'default':'not found'}
        try:
            # This is the most obvious place to acquire the lock, because a
            # malicious user could conceivably flood the bot with rss commands
            # and DoS the website in question.
            self.acquireLock(src)
            if self.willGetStatusUpdate(src):
                results = status.get(src)
                if results and results != self.cachedStatus[src]:
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
                return error('Unable to download feed.')
        finally:
            self.releaseLock(src)

    def makeStatusCommand(self, name, src):
        docstring = format("""[<format>]

        Reports the status for %s at the HackerspaceStatus feed %u.  If
        <format> is given, returns that format.
        HackerspaceStatus feeds are only looked up every supybot.plugins.HackerspaceStatus.waitPeriod
        seconds, which defaults to 120 (2 minutes) since that's what we chose
        randomly.
        """, name, src)
        if src not in self.locks:
            self.locks[src] = threading.RLock()
        if self.isCommandMethod(name):
            s = format('I already have a record for a hackerspace named %s.',name)
            raise callbacks.Error, s
        def f(self, irc, msg, args):
            args.insert(0, src)
            self.hss(irc, msg, args)
        f = utils.python.changeFunctionName(f, name, docstring)
        f = new.instancemethod(f, self, HackerspaceStatus)
        self.hacker_space_names[name] = (src, f)
        self._registerStatus(name, src)
 
    def hss(self, irc, msg, args, src, msg_format):
        """<src> [<format>]

        Gets the status of the given hackerspace.
        If <format> is given, return that format if available.
        """
        self.log.debug('Fetching %u', src)
        status = self.getStatus(src)
        if irc.isChannel(msg.args[0]):
            channel = msg.args[0]
        else:
            channel = None
        status = self.getStatus(status)
        if msg_format:
            status = status[msg_format]
        else:
            status = status['default']
        irc.replies(status)
    hss = wrap(hss, ['text', additional('text')])

Class = HackerspaceStatus

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
