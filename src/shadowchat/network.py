import asyncio
import json
import socket
import struct

from shadowchat.constants import MCAST_GRP, MCAST_PORT


class MulticastProtocol(asyncio.DatagramProtocol):
    def __init__(self, msg_queue: asyncio.Queue):
        self._queue = msg_queue
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
            self._queue.put_nowait(msg)
        except Exception:
            pass

    def send(self, msg: dict):
        if self.transport:
            try:
                data = json.dumps(msg).encode("utf-8")
                self.transport.sendto(data, (MCAST_GRP, MCAST_PORT))
            except Exception:
                pass


def create_multicast_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except AttributeError:
        pass
    sock.bind(("", MCAST_PORT))
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    sock.setblocking(False)
    return sock
