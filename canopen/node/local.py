import logging
import struct

from .base import BaseNode
from ..sdo import SdoServer, SdoAbortedError
from ..nmt import NmtSlave
from .. import objectdictionary


logger = logging.getLogger(__name__)


class LocalNode(BaseNode):

    def __init__(self, node_id, object_dictionary):
        super(LocalNode, self).__init__(node_id, object_dictionary)

        self.data_store = {}
        self._read_callbacks = []
        self._write_callbacks = []

        self.sdo = SdoServer(0x600 + self.id, 0x580 + self.id, self)
        self.nmt = NmtSlave(self.id, self)
        # Let self.nmt handle writes for 0x1017
        self.add_write_callback(self.nmt.on_write)

    def associate_network(self, network):
        self.network = network
        self.sdo.network = network
        self.nmt.network = network
        network.subscribe(self.sdo.rx_cobid, self.sdo.on_request)
        network.subscribe_nmt_cmd(self.id, self.nmt.on_command)

    def remove_network(self):
        self.network.unsubscribe(self.sdo.rx_cobid)
        self.network.unsubscribe_nmt_cmd(self.id)
        self.network = None
        self.sdo.network = None
        self.nmt.network = None

    def add_read_callback(self, callback):
        self._read_callbacks.append(callback)

    def add_write_callback(self, callback):
        self._write_callbacks.append(callback)

    def get_data(self, index, subindex):
        obj = self._find_object(index, subindex)

        # Try callback
        for callback in self._read_callbacks:
            result = callback(index=index, subindex=subindex, od=obj)
            if result is not None:
                return obj.encode_raw(result)

        # Try stored data
        try:
            return self.data_store[index][subindex]
        except KeyError:
            # Try default value
            if obj.default is None:
                # Resource not available
                logger.info("Resource unavailable for 0x%X:%d", index, subindex)
                raise SdoAbortedError(0x060A0023)
            return obj.encode_raw(obj.default)

    def set_data(self, index, subindex, data):
        obj = self._find_object(index, subindex)

        # Try callback
        for callback in self._write_callbacks:
            status = callback(index=index, subindex=subindex, od=obj, data=data)
            if status:
                break

        # Store data
        self.data_store.setdefault(index, {})
        self.data_store[index][subindex] = bytes(data)

    def _find_object(self, index, subindex):
        if index not in self.object_dictionary:
            # Index does not exist
            raise SdoAbortedError(0x06020000)
        obj = self.object_dictionary[index]
        if not isinstance(obj, objectdictionary.Variable):
            # Group or array
            if subindex not in obj:
                # Subindex does not exist
                raise SdoAbortedError(0x06090011)
            obj = obj[subindex]
        return obj