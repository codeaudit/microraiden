import json
import types

import pytest
import requests_mock
from eth_utils import encode_hex
from munch import Munch
from requests.exceptions import SSLError

from microraiden import HTTPHeaders
from microraiden import DefaultHTTPClient
from microraiden.test.utils.client import patch_on_http_response
from microraiden.test.utils.disable_ssl_check import disable_ssl_check


def check_response(response: bytes):
    assert response and response.decode().strip() == '"HI I AM A DOGGO"'


def test_full_cycle_success(
        default_http_client: DefaultHTTPClient,
        api_endpoint_address: str,
        token_contract_address,
        channel_manager_contract_address,
        receiver_address
):
    default_http_client.initial_deposit = lambda x: x

    with requests_mock.mock() as server_mock:
        headers1 = Munch()
        headers1.token_address = token_contract_address
        headers1.contract_address = channel_manager_contract_address
        headers1.receiver_address = receiver_address
        headers1.price = '7'

        headers2 = Munch()
        headers2.cost = '7'

        headers1 = HTTPHeaders.serialize(headers1)
        headers2 = HTTPHeaders.serialize(headers2)

        url = 'http://{}/something'.format(api_endpoint_address)
        server_mock.get(url, [
            {'status_code': 402, 'headers': headers1},
            {'status_code': 200, 'headers': headers2, 'text': 'success'}
        ])
        resource = default_http_client.run('something')

    # First cycle, request price.
    request = server_mock.request_history[0]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address

    # Second cycle, pay price.
    request = server_mock.request_history[1]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address
    assert request.headers['RDN-Balance'] == '7'
    assert default_http_client.channel.balance == 7
    balance_sig_hex = encode_hex(default_http_client.channel.balance_sig)
    assert request.headers['RDN-Balance-Signature'] == balance_sig_hex
    assert default_http_client.channel.balance_sig
    assert resource == b'success'


def test_full_cycle_adapt_balance(
        default_http_client: DefaultHTTPClient,
        api_endpoint_address: str,
        token_contract_address,
        channel_manager_contract_address,
        receiver_address
):
    # Simulate a lost balance signature.
    client = default_http_client.client
    channel = client.get_suitable_channel(receiver_address, 10, initial_deposit=lambda x: 2 * x)
    channel.create_transfer(3)
    lost_balance_sig = channel.balance_sig
    channel.update_balance(0)

    with requests_mock.mock() as server_mock:
        headers1 = Munch()
        headers1.token_address = token_contract_address
        headers1.contract_address = channel_manager_contract_address
        headers1.receiver_address = receiver_address
        headers1.price = '7'

        headers2 = headers1.copy()
        headers2.invalid_amount = '1'
        headers2.sender_balance = '3'
        headers2.balance_signature = encode_hex(lost_balance_sig)

        headers3 = Munch()
        headers3.cost = '7'

        headers1 = HTTPHeaders.serialize(headers1)
        headers2 = HTTPHeaders.serialize(headers2)
        headers3 = HTTPHeaders.serialize(headers3)

        url = 'http://{}/something'.format(api_endpoint_address)
        server_mock.get(url, [
            {'status_code': 402, 'headers': headers1},
            {'status_code': 402, 'headers': headers2},
            {'status_code': 200, 'headers': headers3, 'text': 'success'}
        ])

        resource = default_http_client.run('something')

    # First cycle, request price.
    request = server_mock.request_history[0]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address

    # Second cycle, pay price based on outdated balance.
    request = server_mock.request_history[1]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address
    assert request.headers['RDN-Balance'] == '7'
    assert request.headers['RDN-Balance-Signature']

    # Third cycle, adapt new balance and pay price again.
    request = server_mock.request_history[2]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address
    assert request.headers['RDN-Balance'] == '10'
    assert default_http_client.channel.balance == 10
    balance_sig_hex = encode_hex(default_http_client.channel.balance_sig)
    assert request.headers['RDN-Balance-Signature'] == balance_sig_hex
    assert default_http_client.channel.balance_sig
    assert resource == b'success'


def test_full_cycle_error_500(
        default_http_client: DefaultHTTPClient,
        api_endpoint_address: str,
        token_contract_address,
        channel_manager_contract_address,
        receiver_address
):
    default_http_client.initial_deposit = lambda x: x

    with requests_mock.mock() as server_mock:
        headers1 = Munch()
        headers1.token_address = token_contract_address
        headers1.contract_address = channel_manager_contract_address
        headers1.receiver_address = receiver_address
        headers1.price = '3'

        headers2 = Munch()
        headers2.cost = '3'

        headers1 = HTTPHeaders.serialize(headers1)
        headers2 = HTTPHeaders.serialize(headers2)

        url = 'http://{}/something'.format(api_endpoint_address)
        server_mock.get(url, [
            {'status_code': 402, 'headers': headers1},
            {'status_code': 500, 'headers': {}},
            {'status_code': 200, 'headers': headers2, 'text': 'success'}
        ])
        resource = default_http_client.run('something')

    # First cycle, request price.
    request = server_mock.request_history[0]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address

    # Second cycle, pay price but receive error.
    request = server_mock.request_history[1]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address
    assert request.headers['RDN-Balance'] == '3'
    assert default_http_client.channel.balance == 3
    balance_sig_hex = encode_hex(default_http_client.channel.balance_sig)
    assert request.headers['RDN-Balance-Signature'] == balance_sig_hex

    # Third cycle, retry naively.
    request = server_mock.request_history[2]
    assert request.path == '/something'
    assert request.method == 'GET'
    assert request.headers['RDN-Contract-Address'] == channel_manager_contract_address
    assert request.headers['RDN-Balance'] == '3'
    assert default_http_client.channel.balance == 3
    assert request.headers['RDN-Balance-Signature'] == balance_sig_hex
    assert default_http_client.channel.balance_sig
    assert resource == b'success'


def test_cheating_client(doggo_proxy, default_http_client: DefaultHTTPClient):
    """this test scenario where client sends less funds than what is requested
        by the server. In such case, a "RDN-Invalid-Amount=1" header should
        be sent in a server's reply
    """
    def patched_payment(self: DefaultHTTPClient, receiver: str, price: int):
        return DefaultHTTPClient.on_payment_requested(self, receiver, price + self.price_adjust)

    def patched_on_invalid_amount(self, price: int, balance: int, balance_sig: bytes):
        self.invalid_amount_received += 1
        DefaultHTTPClient.on_invalid_amount(self, price, balance, balance_sig)
        # on_invalid_amount will already prepare the next payment which we don't execute anymore,
        # so revert that.
        self.channel.update_balance(self.channel.balance - price)
        return False

    default_http_client.on_invalid_amount = types.MethodType(
        patched_on_invalid_amount,
        default_http_client
    )
    default_http_client.on_payment_requested = types.MethodType(
        patched_payment,
        default_http_client
    )

    default_http_client.invalid_amount_received = 0

    # correct amount
    default_http_client.price_adjust = 0
    response = default_http_client.run('doggo.jpg')
    check_response(response)
    assert default_http_client.invalid_amount_received == 0
    # underpay
    default_http_client.price_adjust = -1
    response = default_http_client.run('doggo.jpg')
    assert response is None
    assert default_http_client.invalid_amount_received == 1
    # overpay
    default_http_client.price_adjust = 1
    response = default_http_client.run('doggo.jpg')
    assert response is None
    assert default_http_client.invalid_amount_received == 2


def test_default_http_client(
        doggo_proxy,
        default_http_client: DefaultHTTPClient,
        sender_address,
        receiver_address
):
    check_response(default_http_client.run('doggo.jpg'))

    client = default_http_client.client
    open_channels = client.get_open_channels()
    assert len(open_channels) == 1

    channel = open_channels[0]
    assert channel == default_http_client.channel
    assert channel.balance_sig
    assert channel.balance < channel.deposit
    assert channel.sender == sender_address
    assert channel.receiver == receiver_address


def test_default_http_client_topup(doggo_proxy, default_http_client: DefaultHTTPClient):

    # Create a channel that has just enough capacity for one transfer.
    default_http_client.initial_deposit = lambda x: 0
    check_response(default_http_client.run('doggo.jpg'))

    client = default_http_client.client
    open_channels = client.get_open_channels()
    assert len(open_channels) == 1
    channel1 = open_channels[0]
    assert channel1 == default_http_client.channel
    assert channel1.balance_sig
    assert channel1.balance == channel1.deposit

    # Do another payment. Topup should occur.
    check_response(default_http_client.run('doggo.jpg'))
    open_channels = client.get_open_channels()
    assert len(open_channels) == 1
    channel2 = open_channels[0]
    assert channel2 == default_http_client.channel
    assert channel2.balance_sig
    assert channel2.balance < channel2.deposit
    assert channel1 == channel2


def test_default_http_client_close(doggo_proxy, default_http_client: DefaultHTTPClient):
    client = default_http_client.client
    check_response(default_http_client.run('doggo.jpg'))
    default_http_client.close_active_channel()
    open_channels = client.get_open_channels()
    assert len(open_channels) == 0


def test_default_http_client_existing_channel(
        doggo_proxy,
        default_http_client: DefaultHTTPClient,
        receiver_privkey,
        receiver_address
):
    client = default_http_client.client
    channel = client.open_channel(receiver_address, 50)
    check_response(default_http_client.run('doggo.jpg'))
    assert channel.balance == 2
    assert channel.deposit == 50


def test_default_http_client_existing_channel_topup(
        doggo_proxy,
        default_http_client: DefaultHTTPClient,
        receiver_address
):
    client = default_http_client.client
    default_http_client.topup_deposit = lambda x: 13
    channel = client.open_channel(receiver_address, 1)
    check_response(default_http_client.run('doggo.jpg'))
    assert channel.balance == 2
    assert channel.deposit == 13


def test_coop_close(doggo_proxy, default_http_client: DefaultHTTPClient):
    check_response(default_http_client.run('doggo.jpg'))

    client = default_http_client.client
    open_channels = client.get_open_channels()
    assert len(open_channels) == 1

    channel = open_channels[0]
    import requests
    reply = requests.get('http://localhost:5000/api/1/channels/%s/%s' %
                         (channel.sender, channel.block))
    assert reply.status_code == 200
    json_reply = json.loads(reply.text)

    request_data = {'balance': json_reply['balance']}
    reply = requests.delete('http://localhost:5000/api/1/channels/%s/%s' %
                            (channel.sender, channel.block), data=request_data)

    assert reply.status_code == 200


@pytest.mark.parametrize('proxy_ssl', [1])
def test_ssl_client(doggo_proxy, default_http_client: DefaultHTTPClient):
    default_http_client.use_ssl = True
    with disable_ssl_check():
        check_response(default_http_client.run('doggo.jpg'))
    with pytest.raises(SSLError):
        check_response(default_http_client.run('doggo.jpg'))


def test_status_codes(doggo_proxy, default_http_client):
    patch_on_http_response(default_http_client, abort_on=[404])
    default_http_client.run('doggo.jpg')
    assert default_http_client.last_response.status_code == 200
    default_http_client.run('does-not-exist')
    assert default_http_client.last_response.status_code == 404
