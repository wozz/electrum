from PyQt4.Qt import QMessageBox, QDialog, QVBoxLayout, QLabel, QThread, SIGNAL
import PyQt4.QtCore as QtCore
from binascii import unhexlify
from struct import pack
from sys import stderr
from time import sleep
from base64 import b64encode, b64decode

from electrum_gui.qt.password_dialog import make_password_dialog, run_password_dialog
from electrum_gui.qt.util import ok_cancel_buttons
from electrum.account import BIP32_Account
from electrum.bitcoin import EncodeBase58Check, public_key_to_bc_address
from electrum.i18n import _
from electrum.plugins import BasePlugin
from electrum.transaction import deserialize
from electrum.wallet import NewWallet


try:
    from trezorlib.client import types
    from trezorlib.client import proto, BaseClient, ProtocolMixin
    from trezorlib.qt.pinmatrix import PinMatrixWidget
    from trezorlib.transport import ConnectionError
    from trezorlib.transport_hid import HidTransport
    TREZOR = True
except ImportError:
    TREZOR = False

def log(msg):
    stderr.write("%s\n" % msg)
    stderr.flush()

class Plugin(BasePlugin):

    def fullname(self): return 'Trezor Wallet'

    def description(self): return 'Provides support for Trezor hardware wallet\n\nRequires github.com/trezor/python-trezor'

    def __init__(self, gui, name):
        BasePlugin.__init__(self, gui, name)
        self._is_available = self._init()
        self.wallet = None

    def _init(self):
        return TREZOR

    def is_available(self):
        return self._is_available

    def set_enabled(self, enabled):
        self.wallet.storage.put('use_' + self.name, enabled)

    def is_enabled(self):
        if not self.is_available():
            return False

        if not self.wallet or self.wallet.storage.get('wallet_type') == 'trezor':
            return True

        return self.wallet.storage.get('use_' + self.name) is True

    def enable(self):
        return BasePlugin.enable(self)

    def load_wallet(self, wallet):
        self.wallet = wallet

    def add_wallet_types(self, wallet_types):
        wallet_types.append(('trezor', _("Trezor wallet"), TrezorWallet))

    def installwizard_restore(self, wizard, storage):
        wallet = TrezorWallet(storage)
        wallet.create_accounts(None)
        return wallet

    def send_tx(self, tx):
        try:
            self.wallet.sign_transaction(tx, None, None)
        except Exception as e:
            tx.error = str(e)


class TrezorWallet(NewWallet):

    def __init__(self, storage):
        self.transport = None
        self.client = None
        self.mpk = None

        NewWallet.__init__(self, storage)

        self.seed = 'trezor'
        
        self.storage.put('gap_limit', 20, False)    #obey BIP44 gap limit of 20

        self.use_encryption = False

        self.storage.put('seed', self.seed, False)
        self.storage.put('seed_version', self.seed_version, False)
        self.storage.put('use_encryption', self.use_encryption, False)

        self.device_checked = False

    def get_action(self):
        if not self.accounts:
            return 'create_accounts'

    def can_create_accounts(self):
        return True

    def is_watching_only(self):
        return False

    def default_account(self):
        return "44'/0'/0'"

    def get_client(self):
        if not TREZOR:
            raise Exception('please install github.com/trezor/python-trezor')

        if not self.client or self.client.bad:
            try:
                d = HidTransport.enumerate()[0]
                self.transport = HidTransport(d)
            except:
                raise Exception("Trezor not found")
            self.client = QtGuiTrezorClient(self.transport)
            self.client.set_tx_api(self)
            #self.client.clear_session()# TODO Doesn't work with firmware 1.1, returns proto.Failure
            self.client.bad = False
            self.device_checked = False
            self.proper_device = False
        return self.client

    def account_id(self, i):
        return "44'/0'/%d'"%i

    def address_id(self, address):
        account_id, (change, address_index) = self.get_address_index(address)
        return "%s/%d/%d" % (account_id, change, address_index)

    def create_accounts(self, password):
        self.create_account('Main account', '') #name, empty password

    def make_account(self, account_id, password):
        xpub = self.get_public_key(account_id)
        self.add_master_public_key(account_id, xpub)
        account = BIP32_Account({'xpub':xpub})
        return account

    def get_public_key(self, bip32_path):
        address_n = self.get_client().expand_path(bip32_path)
        node = self.get_client().get_public_node(address_n).node
        xpub = "0488B21E".decode('hex') + chr(node.depth) + self.i4b(node.fingerprint) + self.i4b(node.child_num) + node.chain_code + node.public_key
        return EncodeBase58Check(xpub)

    def get_master_public_key(self):
        if not self.mpk:
            self.mpk = self.get_public_key("44'/0'")
        return self.mpk

    def i4b(self, x):
        return pack('I', x)

    def add_keypairs(self, tx, keypairs, password):
        #do nothing - no priv keys available
        pass

    def decrypt_message(self, pubkey, message, password):
        try:
            address = public_key_to_bc_address(pubkey.decode('hex'))
            address_path = self.address_id(address)
            address_n = self.get_client().expand_path(address_path)
        except Exception, e:
            raise e
        try:
            decrypted_msg = self.get_client().decrypt_message(address_n, b64decode(message))
        except Exception, e:
            raise e
        finally:
            twd.emit(SIGNAL('trezor_done'))
        return str(decrypted_msg)

    def sign_message(self, address, message, password):
        try:
            address_path = self.address_id(address)
            address_n = self.get_client().expand_path(address_path)
        except Exception, e:
            raise
        try:
            msg_sig = self.get_client().sign_message('Bitcoin', address_n, message)
        except Exception, e:
            raise e
        finally:
            twd.emit(SIGNAL('trezor_done'))
        b64_msg_sig = b64encode(msg_sig.signature)
        return str(b64_msg_sig)

    def sign_transaction(self, tx, keypairs, password):
        if tx.error or tx.is_complete():
            return

        if not self.check_proper_device():
            raise Exception('Wrong device or password')

        inputs = self.tx_inputs(tx)
        outputs = self.tx_outputs(tx)
        try:
            signed_tx = self.get_client().sign_tx('Bitcoin', inputs, outputs)[1]
        except Exception, e:
            raise e
        finally:
            twd.emit(SIGNAL('trezor_done'))
        values = [i['value'] for i in tx.inputs]
        raw = signed_tx.encode('hex')
        tx.update(raw)
        for i, txinput in enumerate(tx.inputs):
            txinput['value'] = values[i]

    def tx_inputs(self, tx):
        inputs = []

        for txinput in tx.inputs:
            txinputtype = types.TxInputType()
            address = txinput['address']
            try:
                address_path = self.address_id(address)
                address_n = self.get_client().expand_path(address_path)
                txinputtype.address_n.extend(address_n)
            except: pass

            if ('is_coinbase' in txinput and txinput['is_coinbase']):
                prev_hash = "\0"*32
                prev_index = 0xffffffff # signed int -1               
            else:        
                prev_hash = unhexlify(txinput['prevout_hash'])
                prev_index = txinput['prevout_n']

            txinputtype.prev_hash = prev_hash
            txinputtype.prev_index = prev_index

            if 'scriptSig' in txinput:
                script_sig = txinput['scriptSig']
                txinputtype.script_sig = script_sig

            if 'sequence' in txinput:
                sequence = txinput['sequence']
                txinputtype.sequence = sequence

            inputs.append(txinputtype)
            #TODO P2SH
        return inputs

    def tx_outputs(self, tx):
        outputs = []

        for type, address, amount in tx.outputs:
            txoutputtype = types.TxOutputType()

            if self.is_change(address):
                address_path = self.address_id(address)
                address_n = self.get_client().expand_path(address_path)
                txoutputtype.address_n.extend(address_n)
            else:
                txoutputtype.address = address

            txoutputtype.amount = amount

            txoutputtype.script_type = types.PAYTOADDRESS
            #TODO
            #if output['is_p2sh']:
            #    txoutputtype.script_type = types.PAYTOSCRIPTHASH

            outputs.append(txoutputtype)
        return outputs

    def electrum_tx_to_txtype(self, tx):
        t = types.TransactionType()
        d = deserialize(tx.raw)
        t.version = d['version']
        t.lock_time = d['lockTime']

        inputs = self.tx_inputs(tx)
        t.inputs.extend(inputs)

        for vout in d['outputs']:
            o = t.bin_outputs.add()
            o.amount = vout['value']
            o.script_pubkey = vout['scriptPubKey'].decode('hex')

        return t

    def get_tx(self, tx_hash):
        tx = self.transactions[tx_hash]
        return self.electrum_tx_to_txtype(tx)

    def check_proper_device(self):
        self.get_client().ping('t')
        if not self.device_checked:
            address = self.addresses(False, False)[0]
            address_id = self.address_id(address)
            n = self.get_client().expand_path(address_id)
            device_address = self.get_client().get_address('Bitcoin', n)
            self.device_checked = True

            if device_address != address:
                self.proper_device = False
            else:
                self.proper_device = True

        return self.proper_device


class TrezorQtGuiMixin(object):

    def __init__(self, *args, **kwargs):
        super(TrezorQtGuiMixin, self).__init__(*args, **kwargs)

    def callback_ButtonRequest(self, msg):
        if msg.code == 3:
            message = "Confirm transaction outputs on Trezor device to continue"
        elif msg.code == 8:
            message = "Confirm transaction fee on Trezor device to continue"
        elif msg.code == 7:
            message = "Confirm message to sign on Trezor device to continue"
        else:
            message = "Check Trezor device to continue"
        twd.start(message)
        return proto.ButtonAck()

    def callback_PinMatrixRequest(self, msg):
        if msg.type == 1:
            desc = 'old PIN'
        elif msg.type == 2:
            desc = 'new PIN'
        elif msg.type == 3:
            desc = 'new PIN again'
        else:
            desc = 'PIN'

        pin = self.pin_dialog(msg="Please enter Trezor %s" % desc)
        if not pin:
            return proto.Cancel()
        return proto.PinMatrixAck(pin=pin)

    def callback_PassphraseRequest(self, msg):
        confirmed, p, passphrase = self.password_dialog()
        if not confirmed:
            QMessageBox.critical(None, _('Error'), _("Password request canceled"), _('OK'))
            return proto.Cancel()
        if passphrase is None:
            passphrase='' # Even blank string is valid Trezor passphrase
        return proto.PassphraseAck(passphrase=passphrase)

    def callback_WordRequest(self, msg):
        #TODO
        log("Enter one word of mnemonic: ")
        word = raw_input()
        return proto.WordAck(word=word)

    def password_dialog(self, msg=None):
        if not msg:
            msg = _("Please enter your Trezor password")

        d = QDialog()
        d.setModal(1)
        d.setLayout( make_password_dialog(d, None, msg, False) )
        return run_password_dialog(d, None, None)

    def pin_dialog(self, msg):
        d = QDialog(None)
        d.setModal(1)
        d.setWindowTitle(_("Enter PIN"))
        matrix = PinMatrixWidget()

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(msg))
        vbox.addWidget(matrix)
        vbox.addLayout(ok_cancel_buttons(d))
        d.setLayout(vbox)

        if not d.exec_(): return
        return str(matrix.get_value())

class TrezorWaitingDialog(QThread):
    def __init__(self):
        QThread.__init__(self)
        self.waiting = False

    def start(self, message):
        self.d = QDialog()
        self.d.setModal(1)
        self.d.setWindowTitle('Please Check Trezor Device')
        self.d.setWindowFlags(self.d.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        l = QLabel(message)
        vbox = QVBoxLayout(self.d)
        vbox.addWidget(l)
        self.d.show()
        if not self.waiting:
            self.waiting = True
            self.d.connect(twd, SIGNAL('trezor_done'), self.stop)

    def stop(self):
        self.d.hide()
        self.waiting = False


if TREZOR:
    class QtGuiTrezorClient(ProtocolMixin, TrezorQtGuiMixin, BaseClient):
        def call_raw(self, msg):
            try:
                resp = BaseClient.call_raw(self, msg)
            except ConnectionError:
                self.bad = True
                raise
    
            return resp

    twd = TrezorWaitingDialog()

