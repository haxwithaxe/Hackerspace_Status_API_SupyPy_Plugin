###
#
###

from supybot.test import *

url = 'http://'
class HackerspaceStatusTestCase(ChannelPluginTestCase):
    plugins = ('HackerspaceStatus','Plugin')
    def testRssAddBadName(self):
        self.assertError('hss add "foo bar" %s' % url)

    def testCantAddFeedNamedRss(self):
        self.assertError('hss add hss %s' % url)

    def testCantRemoveMethodThatIsntFeed(self):
        self.assertError('hss remove hss')

    if network:
        def testRssinfo(self):
            self.assertNotError('hss info %s' % url)
            self.assertNotError('hss add advogato %s' % url)
            self.assertNotError('hss info advogato')
            self.assertNotError('hss info AdVogATo')
            self.assertNotError('hss remove advogato')

        def testRssinfoDoesTimeProperly(self):
            self.assertNotRegexp('hss info http://', '-1 years')

        def testAnnounce(self):
            self.assertNotError('hss add advogato %s' % url)
            self.assertNotError('hss announce add advogato')
            self.assertNotRegexp('hss announce', r'ValueError')
            self.assertNotError('hss announce remove advogato')
            self.assertNotError('hss remove advogato')

        def testRss(self):
            self.assertNotError('hss %s' % url)
            m = self.assertNotError('hss %s 2' % url)
            self.failUnless(m.args[1].count('||') == 1)

        def testRssAdd(self):
            self.assertNotError('hss add advogato %s' % url)
            self.assertNotError('advogato')
            self.assertNotError('hss advogato')
            self.assertNotError('hss remove advogato')
            self.assertNotRegexp('list HackerspaceStatus', 'advogato')
            self.assertError('advogato')
            self.assertError('hss advogato')

        def testNonAsciiFeeds(self):
            self.assertNotError('hss http://')
            self.assertNotError('hss http://')
            self.assertNotError('hss info http://')

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
