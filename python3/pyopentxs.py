import os
import re
import io
import shutil
from bs4 import BeautifulSoup
from contextlib import closing
"""
This file is a small abstraction layer for the SWIG-generated python API
and does the required initialization on import.

The goal also is to capture errors gracefully.
"""

import opentxs


class ReturnValueError(BaseException):
    """
    The return value of an API function has signaled an error condition
    """
    def __init__(self, return_value):
        self.return_value = return_value

    def __str__(self):
        return "API function has returned error value %r" % self.return_value


class ProcessUserCommand:
    """
    These return values are used by ProcessUserCommand() and bubble up
    to different higher-level APIs. The return value is documented in
    OTClient::ProcessUserCommand()
    """

    # error, don't send message
    Error = 0               # error, don't send message

    # no error, no message sent
    NoMessageSent = -1

    # Paraphrasing the documentation
    # message is sent, no request number returns > 0 for
    # processInbox, containing the number that was there
    # before processing -- FIXME unclear
    MessageSent = 1

    # This is sometimes returned by  OTClient::CalcReturnVal()
    # Low-level networking error
    RequestNumberMismatch = -2


def _remove_pid():
    """
    Remove the PID file if one exists
    """

    # There should not be a long-running opentxs client running anyway.
    # An existing PID file probably indicates a crashed process, not a running
    # instance
    pid_file = os.path.expanduser("~/.ot/client_data/ot.pid")
    if os.path.exists(pid_file):
        print("removing lockfile %s" % pid_file)
        os.remove(pid_file)


def decode(stream):
    ''', and return as string'''
    with closing(stream):
        decoded = opentxs.OTAPI_Wrap_Decode(stream.read(), True)
    return decoded

config_dir = os.environ['HOME'] + "/.ot/"


def init():
    """
    Initialize the OTAPI in order to get a working state
    """
    # This should only be done once per process.
    _remove_pid()
    opentxs.OTAPI_Wrap_AppInit()
    opentxs.OTAPI_Wrap_LoadWallet()


# OTME = OpenTransactions MadeEasy
_otme = opentxs.OT_ME()


# API methods that DONT include server communication

def create_pseudonym(keybits=1024, nym_id_source="", alt_location=""):
    """
    Create a new pseudonym in the local wallet.

    Crashes with OT_FAIL if keysize is invalid.

    Returns generated pseudonym id.
    """
    retval = _otme.create_nym(keybits, nym_id_source, alt_location)

    if retval == '':
        # the pseudonym id should be a 43-byte hash
        raise ReturnValueError(retval)

    return retval


def check_user(server, nym, target_nym):
    # TODO
    # see ot wiki "API" / "Write a checkque"
    return _otme.check_user(server, nym, target_nym)


def create_account(server_id, nym_id, asset_id):
    account_xml = _otme.create_asset_acct(server_id, nym_id, asset_id)

    valid_xml = re.sub("<@createAccount", "<createAccount", account_xml)
    s = BeautifulSoup(valid_xml)

    return s.createaccount['accountid']


def add_server(nym_id, contract):
    '''Create a server contract with the given nym_id and the contract
    contents.'''
    contract_id = opentxs.OTAPI_Wrap_CreateServerContract(nym_id, contract)
    assert(len(contract_id) > 0)
    return contract_id

# Wallet operations
#
# These methods (probably) return the data stored in the local wallet
#


def get_nym_ids():
    """
    Return list of locally stored nyms.
    """
    nym_count = opentxs.OTAPI_Wrap_GetNymCount()
    nym_ids = []
    for i in range(nym_count):
        retval = opentxs.OTAPI_Wrap_GetNym_ID(i)
        if retval == '':
            # this is just a guess, a nym_id should never be an empty string
            raise ReturnValueError(retval)
        nym_ids.append(retval)

    return nym_ids


def get_nym_name(nym_id):
    """
    Return the nym name for a given id.

    Attention: If the nym for the id cannot be found, an empty string is
    returned.
    """

    # FIXME: test and fix crash for empty nym_id
    # FIXME: discern between "empty name" and "nym not found"
    retval = opentxs.OTAPI_Wrap_GetNym_Name(nym_id)

    if retval == '':
        raise ReturnValueError(retval)

    return retval


def get_account_ids():
    account_count = opentxs.OTAPI_Wrap_GetAccountCount()
    accounts = []
    for i in range(account_count):
        account_id = opentxs.OTAPI_Wrap_GetAccountWallet_ID(i)
        accounts.append(account_id)

    return accounts

# API methods that include server communication


def first_server_id():
    return get_servers()[0][0]


def setup_server(contract_stream):
    '''
    Helps create a clean config dir starting from scratch.
    '''
    server_nym = create_pseudonym()
    with closing(contract_stream):
        server_contract = add_server(server_nym, contract_stream.read())
    walletxml = decode(open(config_dir + "client_data/wallet.xml"))
    cached_key = BeautifulSoup(walletxml).wallet.cachedkey.string.strip()
    signed_contract_file = config_dir + "client_data/contracts/" + server_contract
    with closing(open(signed_contract_file)) as f:
        signed_contract = f.read()
    decoded_signed_contract = decode(io.StringIO(signed_contract))

    # copy the credentials to the server
    server_data_dir = config_dir + "server_data/"
    if not os.path.exists(server_data_dir):
        os.mkdir(server_data_dir)
    shutil.copytree(config_dir + "client_data/credentials", server_data_dir + "credentials")
    # remove the client-side data
    shutil.rmtree(config_dir + "client_data")


    # since we still don't have programmatic access, just print the info
    # for easy copying
    print(server_contract)
    print(server_nym)
    print(cached_key + "\n~")
    print(decoded_signed_contract + "\n~")

    # next line crashes the process
    # opentxs.MainFile(None).CreateMainFile(signed_contract, server_contract, "", server_nym,
    # cached_key)
    # add the server contract on the client side
    opentxs.OTAPI_Wrap_AddServerContract(decoded_signed_contract)

    return decoded_signed_contract


def get_servers():
    server_count = opentxs.OTAPI_Wrap_GetServerCount()
    servers = []
    for i in range(server_count):
        server_id = opentxs.OTAPI_Wrap_GetServer_ID(i)
        server_name = opentxs.OTAPI_Wrap_GetServer_Name(server_id)
        servers.append([server_id, server_name])

    return servers


def get_assets():
    """
    Returns an array of assets described as tuples(id, name)
    """
    asset_count = opentxs.OTAPI_Wrap_GetAssetTypeCount()
    assets = []
    for i in range(asset_count):
        asset_id = opentxs.OTAPI_Wrap_GetAssetType_ID(i)
        asset_name = opentxs.OTAPI_Wrap_GetAssetType_Name(asset_id)
        assets.append([asset_id, asset_name])

    return assets

# API methods that include server communication


def check_server_id(server_id, user_id):
    """
    Returns true if the server is available and the user (same as nym) exists.
    """

    # The user_id parameters here is the same as nym_id in other api calls

    # The method is described as a "ping" in the API documentation, which should
    # be called after wallet initialized. However a remote account on the server
    # is required.

    retval = opentxs.OTAPI_Wrap_checkServerID(server_id, user_id)

    print("(debug) check_server_id retval=", retval)

    # The return value `1` for success is defined by
    #     case (OTClient::checkServerId)
    # in OTClient::ProcessUserCommand()

    return retval == 1


def register_nym(server_id, nym_id):
    """
    Register nym on server.

    Returns the response message from the server.
    """
    # TODO: what is the response message?
    message = _otme.register_nym(server_id, nym_id)

    if message == '':
        raise ReturnValueError(message)
    else:
        assert(opentxs.OTAPI_Wrap_Message_GetSuccess(message) == 1)
    return message


def issue_asset_type(server_id, nym_id, contract_stream):
    '''Issues a new asset type on the given server and nym.  contract
    should be a string with the contract contents.

    '''
    # first sign the contract
    asset_id = opentxs.OTAPI_Wrap_CreateAssetContract(nym_id, contract_stream.read())
    assert asset_id
    signed_contract = opentxs.OTAPI_Wrap_getContract(server_id, nym_id, asset_id)
    return _otme.issue_asset_type(server_id, nym_id, signed_contract)


# cleanup methods

def cleanup():
    opentxs.OTAPI_Wrap_AppCleanup()
