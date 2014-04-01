#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2013 thomasv@gitorious
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


from bitcoin import *
from i18n import _
from transaction import Transaction

class Account(object):
    def __init__(self, v):
        self.addresses = v.get('0', [])
        self.change = v.get('1', [])

    def dump(self):
        return {'0':self.addresses, '1':self.change}

    def get_addresses(self, for_change):
        return self.change[:] if for_change else self.addresses[:]

    def create_new_address(self, for_change):
        addresses = self.change if for_change else self.addresses
        n = len(addresses)
        address = self.get_address( for_change, n)
        addresses.append(address)
        print address
        return address

    def get_address(self, for_change, n):
        pass
        
    def get_pubkeys(self, sequence):
        return [ self.get_pubkey( *sequence )]



class OldAccount(Account):
    """  Privatekey(type,n) = Master_private_key + H(n|S|type)  """

    def __init__(self, v):
        self.addresses = v.get(0, [])
        self.change = v.get(1, [])
        self.mpk = v['mpk'].decode('hex')

    def dump(self):
        return {0:self.addresses, 1:self.change}

    @classmethod
    def mpk_from_seed(klass, seed):
        curve = SECP256k1
        secexp = klass.stretch_key(seed)
        master_private_key = ecdsa.SigningKey.from_secret_exponent( secexp, curve = SECP256k1 )
        master_public_key = master_private_key.get_verifying_key().to_string().encode('hex')
        return master_public_key

    @classmethod
    def stretch_key(self,seed):
        oldseed = seed
        for i in range(100000):
            seed = hashlib.sha256(seed + oldseed).digest()
        return string_to_number( seed )

    def get_sequence(self, for_change, n):
        return string_to_number( Hash( "%d:%d:"%(n,for_change) + self.mpk ) )

    def get_address(self, for_change, n):
        pubkey = self.get_pubkey(for_change, n)
        address = public_key_to_bc_address( pubkey.decode('hex') )
        return address

    def get_pubkey(self, for_change, n):
        curve = SECP256k1
        mpk = self.mpk
        z = self.get_sequence(for_change, n)
        master_public_key = ecdsa.VerifyingKey.from_string( mpk, curve = SECP256k1 )
        pubkey_point = master_public_key.pubkey.point + z*curve.generator
        public_key2 = ecdsa.VerifyingKey.from_public_point( pubkey_point, curve = SECP256k1 )
        return '04' + public_key2.to_string().encode('hex')

    def get_private_key_from_stretched_exponent(self, for_change, n, secexp):
        order = generator_secp256k1.order()
        secexp = ( secexp + self.get_sequence(for_change, n) ) % order
        pk = number_to_string( secexp, generator_secp256k1.order() )
        compressed = False
        return SecretToASecret( pk, compressed )
        
    def get_private_key(self, seed, sequence):
        for_change, n = sequence
        secexp = self.stretch_key(seed)
        return self.get_private_key_from_stretched_exponent(for_change, n, secexp)

    def check_seed(self, seed):
        curve = SECP256k1
        secexp = self.stretch_key(seed)
        master_private_key = ecdsa.SigningKey.from_secret_exponent( secexp, curve = SECP256k1 )
        master_public_key = master_private_key.get_verifying_key().to_string()
        if master_public_key != self.mpk:
            print_error('invalid password (mpk)', self.mpk.encode('hex'), master_public_key.encode('hex'))
            raise Exception('Invalid password')
        return True

    def redeem_script(self, sequence):
        return None

    def get_master_pubkeys(self):
        return [self.mpk]

    def get_type(self):
        return _('Old Electrum format')



class BIP32_Account(Account):

    def __init__(self, v):
        Account.__init__(self, v)
        self.xpub = v['xpub']

    def dump(self):
        d = Account.dump(self)
        d['xpub'] = self.xpub
        return d

    def get_address(self, for_change, n):
        pubkey = self.get_pubkey(for_change, n)
        address = public_key_to_bc_address( pubkey.decode('hex') )
        return address

    def first_address(self):
        return self.get_address(0,0)

    def get_pubkey(self, for_change, n):
        _, _, _, c, cK = deserialize_xkey(self.xpub)
        for i in [for_change, n]:
            cK, c = CKD_pub(cK, c, i)
        return cK.encode('hex')

    def redeem_script(self, sequence):
        return None

    def get_pubkeys(self, sequence):
        return [self.get_pubkey(*sequence)]

    def get_master_pubkeys(self):
        return [self.xpub]

    def get_type(self):
        return _('Standard 1 of 1')
        #acctype = 'multisig 2 of 2' if len(roots) == 2 else 'multisig 2 of 3' if len(roots) == 3 else 'standard 1 of 1'


class BIP32_Account_2of2(BIP32_Account):

    def __init__(self, v):
        BIP32_Account.__init__(self, v)
        self.xpub2 = v['xpub2']

    def dump(self):
        d = BIP32_Account.dump(self)
        d['xpub2'] = self.xpub2
        return d

    def get_pubkey2(self, for_change, n):
        _, _, _, c, cK = deserialize_xkey(self.xpub2)
        for i in [for_change, n]:
            cK, c = CKD_pub(cK, c, i)
        return cK.encode('hex')

    def redeem_script(self, sequence):
        chain, i = sequence
        pubkey1 = self.get_pubkey(chain, i)
        pubkey2 = self.get_pubkey2(chain, i)
        return Transaction.multisig_script([pubkey1, pubkey2], 2)

    def get_address(self, for_change, n):
        address = hash_160_to_bc_address(hash_160(self.redeem_script((for_change, n)).decode('hex')), 5)
        return address

    def get_pubkeys(self, sequence):
        return [ self.get_pubkey( *sequence ), self.get_pubkey2( *sequence )]

    def get_master_pubkeys(self):
        return [self.xpub, self.xpub2]

    def get_type(self):
        return _('Multisig 2 of 2')


class BIP32_Account_2of3(BIP32_Account_2of2):

    def __init__(self, v):
        BIP32_Account_2of2.__init__(self, v)
        self.xpub3 = v['xpub3']

    def dump(self):
        d = BIP32_Account_2of2.dump(self)
        d['xpub3'] = self.xpub3
        return d

    def get_pubkey3(self, for_change, n):
        _, _, _, c, cK = deserialize_xkey(self.xpub3)
        for i in [for_change, n]:
            cK, c = CKD_pub(cK, c, i)
        return cK.encode('hex')

    def get_redeem_script(self, sequence):
        chain, i = sequence
        pubkey1 = self.get_pubkey(chain, i)
        pubkey2 = self.get_pubkey2(chain, i)
        pubkey3 = self.get_pubkey3(chain, i)
        return Transaction.multisig_script([pubkey1, pubkey2, pubkey3], 3)

    def get_pubkeys(self, sequence):
        return [ self.get_pubkey( *sequence ), self.get_pubkey2( *sequence ), self.get_pubkey3( *sequence )]

    def get_master_pubkeys(self):
        return [self.xpub, self.xpub2, self.xpub3]

    def get_type(self):
        return _('Multisig 2 of 3')



