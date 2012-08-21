###
#
###

import supybot.conf as conf
import supybot.registry as registry
import supybot.callbacks as callbacks

def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified himself as an advanced
    # user or not.  You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin('HackerspaceStatus', True)


class HackerspaceNames(registry.SpaceSeparatedListOfStrings):
    List = callbacks.CanonicalNameSet

HackerspaceStatus = conf.registerPlugin('HackerspaceStatus')
conf.registerChannelValue(HackerspaceStatus, 'bold', registry.Boolean(
    False, """Determines whether the bot will bold the status message when it
    announces new news."""))
conf.registerChannelValue(HackerspaceStatus, 'headlineSeparator',
    registry.StringSurroundedBySpaces(' ', """Determines what string is used
    to separate statuses in list."""))
conf.registerChannelValue(HackerspaceStatus, 'announcementPrefix',
    registry.StringWithSpaceOnRight('', """Determines what prefix
    is prepended (if any) to the new status message item announcements made in the
    channel."""))
conf.registerChannelValue(HackerspaceStatus, 'announce',
    registry.SpaceSeparatedSetOfStrings([], """Determines which
    status should be announced in the channel; valid input is
    a list of strings (status URLs) separated by spaces."""))

conf.registerGlobalValue(HackerspaceStatus, 'waitPeriod',
    registry.PositiveInteger(120, """Indicates how many seconds the bot will
    wait between retrieving statuses; requests made within this period will
    return cached results."""))

conf.registerGlobalValue(HackerspaceStatus, 'hackerspace_status',
    HackerspaceNames([], """Determines what hackerspace status should be accessible as
    commands."""))

conf.registerGroup(HackerspaceStatus, 'announce')



# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
