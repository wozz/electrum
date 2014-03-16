from PyQt4.QtGui import *
from PyQt4.QtCore import *
from electrum_gui.qt.util import *
from electrum.util import *
from electrum.plugins import BasePlugin
from electrum.i18n import _
from electrum.bitcoin import is_valid

import json
import sys
import httplib



class Plugin(BasePlugin):
    def fullname(self):
        return 'OneName Contacts'

    def description(self):
        return 'Import contacts from the Namecoin blockchain.'

    def __init__(self, gui, name):
        BasePlugin.__init__(self, gui, name)
        self._is_available = True

    def init(self):
        self.win = self.gui.main_window


    def requires_settings(self):
        return True

    def settings_widget(self, window):
        return EnterButton(_('Get Contact'), self.onename_contact_dialog)


    def get_json(self, site, get_string):
        try:
            connection = httplib.HTTPSConnection(site)
            connection.request("GET", get_string)
        except Exception:
            raise
        resp = connection.getresponse()
        if resp.reason == httplib.responses[httplib.NOT_FOUND]:
            raise
        try:
            json_resp = json.loads(resp.read())
        except Exception:
            raise
        return json_resp


    def onename_contact_dialog(self):
       
        d = QDialog(self.win)
        vbox = QVBoxLayout(d)
        vbox.addWidget(QLabel(_('OneName Contact')+':'))

        grid = QGridLayout()
        line1 = QLineEdit()
        line2 = QLineEdit()
        grid.addWidget(QLabel(_("Username")), 1, 0)
        grid.addWidget(line1, 1, 1)

        vbox.addLayout(grid)
        vbox.addLayout(ok_cancel_buttons(d))

        if not d.exec_():
            return

        username = str(line1.text())

        if username[:1] == '+':
            username = username[1:]

        rjson1 = self.get_json('www.onename.io', "/" + username + ".json")
        rjson2 = self.get_json('dns.dnschain.net', "/u/" + username)

        while 'next' in rjson2:
            nextjson = self.get_json('dns.dnschain.net', "/" + rjson2['next'])
            for i in nextjson:
                rjson2[i] = nextjson[i]
            if not 'next' in nextjson:
                break

        if not rjson1['v'] == "0.2":
            QMessageBox.warning(self, _('Error'), _('Incompatible key version'), _('OK'))
            return

        address1 = rjson1['bitcoin']['address']
        address2 = rjson2['bitcoin']['address']

        try:
            label = "+" + username + " (" + rjson1['name']['formatted'] + ")"
        except Exception:
            pass

        if address1 != address2:
            QMessageBox.warning(self, _('Error'), _('Error getting match'), _('OK'))
            return
        else:
            address = address1

        if not is_valid(address):
            QMessageBox.warning(self, _('Error'), _('Invalid Address'), _('OK'))
            return

        d2 = QDialog(self.win)
        vbox2 = QVBoxLayout(d2)
        grid2 = QGridLayout()
        grid2.addWidget(QLabel("+" + username), 1, 1)
        if 'name' in rjson1:
            grid2.addWidget(QLabel('Name: '),2,0)
            grid2.addWidget(QLabel(str(rjson1['name']['formatted'])),2,1)

        if 'location' in rjson1:
            grid2.addWidget(QLabel('Location: '),3,0)
            grid2.addWidget(QLabel(str(rjson1['location']['formatted'])),3,1)

        grid2.addWidget(QLabel('Address: '),4,0)
        grid2.addWidget(QLabel(address),4,1)


        vbox2.addLayout(grid2)
        vbox2.addLayout(ok_cancel_buttons(d2))

        if not d2.exec_():
            return

        self.win.wallet.add_contact(address)
        if label:
            self.win.wallet.set_label(address, label)

        self.win.update_contacts_tab()
        self.win.update_history_tab()
        self.win.update_completions()
        self.win.tabs.setCurrentIndex(3) 
