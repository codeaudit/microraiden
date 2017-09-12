from microraiden import config
from microraiden.crypto import privkey_to_addr

# private key of the content provider
PRIVATE_KEY = 'b6b2c38265a298a5dd24aced04a4879e36b5cc1a4000f61279e188712656e946'
RECEIVER_ADDRESS = privkey_to_addr(PRIVATE_KEY)
# host and port Parity/Geth serves RPC requests on
RPC_PROVIDER = 'http://172.18.0.1:8545'
# state file to store proxy state and balance proofs
STATE_FILE = "/files/%s_%s.pkl" % (config.CHANNEL_MANAGER_ADDRESS[:10], RECEIVER_ADDRESS[:10])
