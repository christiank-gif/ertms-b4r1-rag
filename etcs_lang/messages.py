"""ERTMS/ETCS radio messages per SUBSET-026-8 (Messages).

Standard format of a track-to-train radio message (ch.8 §8.4.4.6):
NID_MESSAGE(8), L_MESSAGE(10), T_TRAIN(32), M_ACK(1), NID_LRBG(24),
then message-specific variables and packets, optional packets, padding.

Train-to-track messages (ch.8 §8.6): NID_MESSAGE, L_MESSAGE, T_TRAIN,
NID_ENGINE(24), then message-specific variables/packets.

L_MESSAGE is the message length in BYTES, including NID_MESSAGE and L_MESSAGE
themselves (SUBSET-026-7 §7.5.1.48, 10 bits, resolution 1 byte; ch.8 §8.4.4.2).
"""

from .bitstream import BitWriter, BitReader
from .variables import (
    encode_bcd, decode_bcd, VARIABLES, encode_distance, decode_distance,
    encode_speed, decode_speed,
)
from .versions import version_code, decode_version_code
from .packets import (
    build_packet, decode_packet, Packet,
    build_packet_0_position_report, build_packet_15_l2_ma,
    build_packet_2_onboard_versions, build_packet_5_train_running_number,
    build_packet_11_train_data, build_packet_4_error_reporting,
)

# Message tables from SUBSET-026-8 §8.5.2 (train to track) and §8.5.3 (track to train)
TRAIN_TO_TRACK_MESSAGES = {
    129: "Validated Train Data",
    130: "Request for Shunting",
    131: "Request for Supervised Manoeuvre",
    132: "MA Request",
    133: "Safe consist length information for SM",
    136: "Train Position Report",
    137: "Request to Shorten MA is granted",
    138: "Request to Shorten MA is rejected",
    146: "Acknowledgement",
    147: "Acknowledgement of Emergency Stop",
    149: "Track Ahead Free Granted",
    150: "End of Mission",
    153: "Radio infill request",
    154: "No compatible version supported",
    155: "Initiation of a communication session",
    156: "Termination of a communication session",
    157: "SoM Position Report",
    158: "Text Message Acknowledged by Driver",
    159: "Session established",
}

TRACK_TO_TRAIN_MESSAGES = {
    2: "SR Authorisation",
    3: "Movement Authority",
    4: "SM Authorisation",
    5: "SM Refused",
    6: "Recognition of exit from TRIP mode",
    7: "Acknowledgment of safe consist length info for SM",
    8: "Acknowledgement of Train Data",
    9: "Request to Shorten MA",
    15: "Conditional Emergency Stop",
    16: "Unconditional Emergency Stop",
    18: "Revocation of Emergency Stop",
    24: "General message",
    27: "SH Refused",
    28: "SH Authorised",
    32: "RBC/RIU System Version",
    33: "MA with Shifted Location Reference",
    34: "Track Ahead Free Request",
    37: "Infill MA",
    38: "Acknowledgement of session establishment",
    39: "Acknowledgement of termination of a communication session",
    40: "Train Rejected",
    41: "Train Accepted",
    43: "SoM position report confirmed by RBC",
    45: "Assignment of coordinate system",
}


class RadioMessage:
    """A decoded Euroradio message."""

    def __init__(self, nid_message, direction, fields=None, packets=None):
        self.nid_message = nid_message
        self.direction = direction
        self.fields = fields or {}
        self.packets = packets or []

    @property
    def title(self):
        table = TRAIN_TO_TRACK_MESSAGES if self.direction == "train_to_track" else TRACK_TO_TRAIN_MESSAGES
        return table.get(self.nid_message, f"Message {self.nid_message}")

    def __repr__(self):
        return f"{self.direction} Message {self.nid_message} ({self.title}) fields={self.fields} packets={self.packets}"


def _patch_l_message(w: BitWriter, pos: int) -> BitWriter:
    """L_MESSAGE (10 bits at pos) = message length in BYTES, header included (ch.7 §7.5.1.48)."""
    l_message = (len(w) + 7) // 8  # total message length in bytes
    bits = w.to_bits()
    for i in range(10):
        bits[pos + i] = (l_message >> (9 - i)) & 1
    nw = BitWriter()
    nw.write_bits(bits)
    return nw


def _finish_message(w: BitWriter, l_pos: int) -> bytes:
    # ch.8 §8.4.4.5: pad with zero bits to an integer number of bytes BEFORE
    # computing L_MESSAGE (message length in bytes, header included).
    while len(w) % 8:
        w.write_uint(0, 1)
    w = _patch_l_message(w, l_pos)
    return w.to_bytes(pad=False)


def build_message(nid_message, direction, t_train, m_ack=0, nid_lrbg=None,
                  nid_engine=None, extra_fields=None, packets=None) -> bytes:
    """Build a Euroradio message (ch.8 §8.4.4.6 / §8.6).

    packets: list of raw packet byte strings to append (already built).
    """
    w = BitWriter()
    w.write_uint(nid_message, 8)
    l_pos = len(w)
    w.write_uint(0, 10)  # L_MESSAGE placeholder
    w.write_uint(int(t_train), 32)  # T_TRAIN (10 ms resolution)
    if direction == "train_to_track":
        w.write_uint(nid_engine, 24)  # NID_ENGINE = NID_C(10)+NID_ENGINE(14)
    else:
        w.write_uint(m_ack, 1)
        w.write_uint(nid_lrbg, 24)  # NID_LRBG = NID_C(10)+NID_BG(14)
    for name, value in (extra_fields or {}).items():
        var = VARIABLES[name]
        w.write_uint(int(value), var.length_bits)
    for pkt in packets or []:
        r = BitReader(pkt)
        while r.remaining():
            w.write_uint(r.read_uint(1), 1)
    return _finish_message(w, l_pos)


def decode_message(data, direction=None) -> RadioMessage:
    """Decode a Euroradio message. Direction is auto-detected from NID_MESSAGE."""
    reader = BitReader(data)
    nid_message = reader.read_uint(8)
    l_message = reader.read_uint(10)
    if direction is None:
        direction = "train_to_track" if nid_message in TRAIN_TO_TRACK_MESSAGES else "track_to_train"
    t_train = reader.read_uint(32)
    fields = {"L_MESSAGE": l_message, "T_TRAIN": t_train}
    if direction == "train_to_track":
        fields["NID_ENGINE"] = reader.read_uint(24)
    else:
        fields["M_ACK"] = reader.read_uint(1)
        fields["NID_LRBG"] = reader.read_uint(24)
    packets = []
    msg_end = l_message * 8 if l_message else len(reader._bits)
    while reader.remaining() >= 8 and reader.pos + 8 <= msg_end:
        peek = reader.peek_uint(8)
        if peek == 255:
            reader.read_uint(8)
            break
        if direction == "train_to_track" and peek == 0:
            pass  # train-to-track packets legitimately start with NID_PACKET=0
        elif peek == 0:
            break  # zero padding / no packet here
        pkt_start = reader.pos
        try:
            pkt = decode_packet(reader, direction)
        except (EOFError, ValueError):
            reader._pos = pkt_start
            break
        packets.append(pkt)
    return RadioMessage(nid_message, direction, fields, packets)


# ---- high-level message builders (ch.8 §8.6 / §8.7) ----------------------------

def msg_155_initiate_session(t_train, nid_engine) -> bytes:
    """Message 155: Initiation of a communication session (train->track, §8.6.13)."""
    return build_message(155, "train_to_track", t_train, nid_engine=nid_engine)


def msg_156_terminate_session(t_train, nid_engine) -> bytes:
    """Message 156: Termination of a communication session (§8.6.14)."""
    return build_message(156, "train_to_track", t_train, nid_engine=nid_engine)


def msg_159_session_established(t_train, nid_engine) -> bytes:
    """Message 159: Session established (§8.6.17)."""
    return build_message(159, "train_to_track", t_train, nid_engine=nid_engine)


def msg_154_no_compatible_version(t_train, nid_engine) -> bytes:
    """Message 154: No compatible version supported (§8.6.12)."""
    return build_message(154, "train_to_track", t_train, nid_engine=nid_engine)


def msg_146_acknowledgement(t_train, nid_engine) -> bytes:
    """Message 146: Acknowledgement (§8.6.7)."""
    return build_message(146, "train_to_track", t_train, nid_engine=nid_engine)


def msg_136_position_report(t_train, nid_engine, q_scale, nid_c, nid_bg,
                            d_lrbg_m, v_train_kmh, m_mode, m_level,
                            q_dirlrbg=0, q_dlrbg=0, l_doubtover_m=0.0,
                            l_doubtunder_m=0.0, q_integrity=0, q_dirtrain=0,
                            nid_ntc=0, extra_packets=None) -> bytes:
    """Message 136: Train Position Report with packet 0 (§8.6.4)."""
    pkt0 = build_packet_0_position_report(
        q_scale, nid_c, nid_bg, d_lrbg_m, q_dirlrbg, q_dlrbg,
        l_doubtover_m, l_doubtunder_m, q_integrity, v_train_kmh,
        q_dirtrain, m_mode, m_level, nid_ntc=nid_ntc)
    return build_message(136, "train_to_track", t_train, nid_engine=nid_engine,
                         packets=[pkt0] + list(extra_packets or []))


def msg_129_validated_train_data(t_train, nid_engine, train_data: dict,
                                 extra_packets=None) -> bytes:
    """Message 129: Validated Train Data with packet 11 (§8.6.1)."""
    pkt11 = build_packet_11_train_data(**train_data)
    return build_message(129, "train_to_track", t_train, nid_engine=nid_engine,
                         packets=[pkt11] + list(extra_packets or []))


def msg_132_ma_request(t_train, nid_engine, extra_packets=None) -> bytes:
    """Message 132: MA Request (§8.6.3)."""
    return build_message(132, "train_to_track", t_train, nid_engine=nid_engine,
                         packets=list(extra_packets or []))


def msg_2_sr_authorisation(t_train, m_ack, nid_lrbg, q_scale, d_sr_m,
                           extra_packets=None) -> bytes:
    """Message 2: SR Authorisation (track->train, §8.7.1)."""
    return build_message(2, "track_to_train", t_train, m_ack=m_ack, nid_lrbg=nid_lrbg,
                         extra_fields={"Q_SCALE": q_scale, "D_SR": round(d_sr_m / 0.10)},
                         packets=list(extra_packets or []))


def msg_3_movement_authority(t_train, m_ack, nid_lrbg, ma_params: dict,
                             extra_packets=None) -> bytes:
    """Message 3: Movement Authority with packet 15 (track->train, §8.7.2)."""
    pkt15 = build_packet_15_l2_ma(**ma_params)
    return build_message(3, "track_to_train", t_train, m_ack=m_ack, nid_lrbg=nid_lrbg,
                         packets=[pkt15] + list(extra_packets or []))


def msg_32_system_version(t_train, m_ack, nid_lrbg, m_version,
                          extra_packets=None) -> bytes:
    """Message 32: RBC/RIU System Version (track->train, §8.7.12)."""
    return build_message(32, "track_to_train", t_train, m_ack=m_ack, nid_lrbg=nid_lrbg,
                         extra_fields={"M_VERSION": version_code(m_version)},
                         packets=list(extra_packets or []))


def msg_16_unconditional_emergency_stop(t_train, m_ack, nid_lrbg,
                                        extra_packets=None) -> bytes:
    """Message 16: Unconditional Emergency Stop (§8.7.7)."""
    return build_message(16, "track_to_train", t_train, m_ack=m_ack, nid_lrbg=nid_lrbg,
                         packets=list(extra_packets or []))


def msg_38_ack_session_establishment(t_train, m_ack, nid_lrbg,
                                     extra_packets=None) -> bytes:
    """Message 38: Acknowledgement of session establishment (§8.7.16)."""
    return build_message(38, "track_to_train", t_train, m_ack=m_ack, nid_lrbg=nid_lrbg,
                         packets=list(extra_packets or []))


def msg_41_train_accepted(t_train, m_ack, nid_lrbg, t_train_msg, extra_packets=None) -> bytes:
    """Message 41: Train Accepted (§8.7.19) — includes T_TRAIN of msg 155."""
    return build_message(41, "track_to_train", t_train, m_ack=m_ack, nid_lrbg=nid_lrbg,
                         extra_fields={"T_TRAIN": int(t_train_msg)},
                         packets=list(extra_packets or []))
