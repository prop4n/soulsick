"""Envoi à un pair au port fermé : sa connexion de fichier « second-chance » (slskd) est acceptée.

Cas réel : rubiksenjoyer (slskd, port fermé) ne pouvait rien télécharger. Notre connexion de fichier
n'aboutissait pas, slskd ouvrait la sienne avec notre ticket, et aioslsk la fermait comme inconnue.
"""

import asyncio
from types import SimpleNamespace

from aioslsk.exceptions import PeerConnectionError

from soulsick.slsk.engine import SafeTransferManager


class _Network:
    def __init__(self, outcome, delay=0.0):
        self.outcome, self.delay = outcome, delay

    async def create_peer_connection(self, username, typ):
        await asyncio.sleep(self.delay)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _manager(network, timeout=1.0):
    return SimpleNamespace(_network=network, FILE_CONNECTION_TIMEOUT=timeout)


async def _race(network, incoming_after=None, incoming_conn="theirs", timeout=1.0):
    incoming = asyncio.get_running_loop().create_future()
    if incoming_after is not None:
        asyncio.get_running_loop().call_later(incoming_after, incoming.set_result, incoming_conn)
    transfer = SimpleNamespace(username="rubiksenjoyer")
    return await SafeTransferManager._file_connection(_manager(network, timeout), transfer, incoming)


async def test_la_connexion_du_pair_est_prise_quand_la_notre_echoue():
    conn, theirs = await _race(_Network(PeerConnectionError("closed port")), incoming_after=0.05)
    assert conn == "theirs" and theirs


async def test_la_notre_est_gardee_quand_elle_aboutit():
    conn, theirs = await _race(_Network("ours"), incoming_after=0.5)
    assert conn == "ours" and not theirs


async def test_la_premiere_prete_gagne():
    conn, theirs = await _race(_Network("ours", delay=0.5), incoming_after=0.05)
    assert conn == "theirs" and theirs


async def test_rien_ne_vient():
    conn, theirs = await _race(_Network(PeerConnectionError("closed port")), timeout=0.2)
    assert conn is None and not theirs
