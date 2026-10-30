"""Eurobalise telegrams and Euroloop messages per SUBSET-026-8 §8.4.2 / §8.4.3.

Balise telegram header (50 bits, §8.4.2.1):
Q_UPDOWN(1), M_VERSION(7), Q_MEDIA(1), N_PIG(3), N_TOTAL(3), M_DUP(2),
M_MCOUNT(8), NID_C(10), NID_BG(14), Q_LINK(1).
Then optional packet 0 (VBC marker, first packet), information packets, and
packet 255 (End of Information).

Loop message header (33 bits, §8.4.3.1):
Q_UPDOWN(1), M_VERSION(7), Q_MEDIA(1), NID_C(10), NID_LOOP(14).
"""

from .bitstream import BitWriter, BitReader
from .versions import version_code, decode_version_code
from .packets import decode_packet, build_packet_255, Packet

BALISE_HEADER_BITS = 50
LOOP_HEADER_BITS = 33


def _read_packets(reader):
    packets = []
    while reader.remaining() >= 8:
        if reader.peek_uint(8) == 255:
            reader.read_uint(8)
            break
        start = reader.pos
        nid = reader.peek_uint(8)
        try:
            if nid == 0:
                # ch.8 §8.4.2.3: packet 0 = NID_PACKET(8) + NID_VBCMK(6) only
                reader.read_uint(8)
                packets.append(Packet(0, "track_to_train", {"NID_VBCMK": reader.read_uint(6)}))
                continue
            pkt = decode_packet(reader, "track_to_train", in_telegram=True)
        except (EOFError, ValueError):
            reader._pos = start
            break
        packets.append(pkt)
    return packets


class BaliseTelegram:
    def __init__(self, fields, packets):
        self.fields = fields
        self.packets = packets

    def __repr__(self):
        return f"BaliseTelegram {self.fields} packets={[p.number for p in self.packets]}"


class LoopMessage:
    def __init__(self, fields, packets):
        self.fields = fields
        self.packets = packets

    def __repr__(self):
        return f"LoopMessage {self.fields} packets={[p.number for p in self.packets]}"


def _append_packet_bits(w: BitWriter, pkt):
    """Append packet bits without byte-alignment (ch.8 §8.4.2.2: packets are not split).
    Accepts bytes or a raw bit list (e.g. the 14-bit packet 0)."""
    bits = pkt if isinstance(pkt, list) else BitReader(pkt).to_bits()
    w.write_bits(bits)


def build_telegram(m_version, n_pig, n_total, m_dup, m_mcount, nid_c, nid_bg,
                   q_link=0, q_updown=1, packets=None) -> bytes:
    """Build one Eurobalise up-link telegram (track-to-train), ch.8 §8.4.2.1."""
    w = BitWriter()
    w.write_uint(q_updown, 1)
    w.write_uint(version_code(m_version), 7)
    w.write_uint(0, 1)  # Q_MEDIA: balise
    w.write_uint(n_pig, 3)
    w.write_uint(n_total, 3)
    w.write_uint(m_dup, 2)
    w.write_uint(m_mcount, 8)
    w.write_uint(nid_c, 10)
    w.write_uint(nid_bg, 14)
    w.write_uint(q_link, 1)
    for pkt in packets or []:
        _append_packet_bits(w, pkt)
    _append_packet_bits(w, build_packet_255())
    return w.to_bytes()


def decode_telegram(data) -> BaliseTelegram:
    """Decode a Eurobalise telegram (ch.8 §8.4.2.1)."""
    reader = BitReader(data)
    fields = {
        "Q_UPDOWN": reader.read_uint(1),
        "M_VERSION": reader.read_uint(7),
        "Q_MEDIA": reader.read_uint(1),
        "N_PIG": reader.read_uint(3),
        "N_TOTAL": reader.read_uint(3),
        "M_DUP": reader.read_uint(2),
        "M_MCOUNT": reader.read_uint(8),
        "NID_C": reader.read_uint(10),
        "NID_BG": reader.read_uint(14),
        "Q_LINK": reader.read_uint(1),
    }
    packets = _read_packets(reader)
    return BaliseTelegram(fields, packets)


def build_loop_message(m_version, nid_c, nid_loop, q_updown=1, packets=None) -> bytes:
    """Build one Euroloop message (track-to-train), ch.8 §8.4.3.1."""
    w = BitWriter()
    w.write_uint(q_updown, 1)
    w.write_uint(version_code(m_version), 7)
    w.write_uint(1, 1)  # Q_MEDIA: loop
    w.write_uint(nid_c, 10)
    w.write_uint(nid_loop, 14)
    for pkt in packets or []:
        _append_packet_bits(w, pkt)
    _append_packet_bits(w, build_packet_255())
    return w.to_bytes()


def decode_loop(data) -> LoopMessage:
    reader = BitReader(data)
    fields = {
        "Q_UPDOWN": reader.read_uint(1),
        "M_VERSION": reader.read_uint(7),
        "Q_MEDIA": reader.read_uint(1),
        "NID_C": reader.read_uint(10),
        "NID_LOOP": reader.read_uint(14),
    }
    packets = _read_packets(reader)
    return LoopMessage(fields, packets)
