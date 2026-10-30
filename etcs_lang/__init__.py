"""ETCS language toolkit based on SUBSET-026 chapters 6, 7 and 8 (B4R1, issue 4.0.0).

Generates and decodes ERTMS/ETCS track-to-train (sol) and train-to-track (bord)
messages, balise telegrams and loop messages conform to the ERTMS/ETCS language.
"""

from .bitstream import BitWriter, BitReader
from .versions import SystemVersion, version_code, parse_version
from .variables import Variable, VARIABLES, encode_variable, decode_variable
from .packets import Packet, build_packet, decode_packet, PACKET_DEFS
from .messages import (
    RadioMessage,
    TRAIN_TO_TRACK_MESSAGES,
    TRACK_TO_TRAIN_MESSAGES,
    build_message,
    decode_message,
)
from .telegram import BaliseTelegram, LoopMessage, build_telegram, decode_telegram
from .generator import MessageGenerator

__all__ = [
    "BitWriter",
    "BitReader",
    "SystemVersion",
    "version_code",
    "parse_version",
    "Variable",
    "VARIABLES",
    "encode_variable",
    "decode_variable",
    "Packet",
    "build_packet",
    "decode_packet",
    "PACKET_DEFS",
    "RadioMessage",
    "TRAIN_TO_TRACK_MESSAGES",
    "TRACK_TO_TRAIN_MESSAGES",
    "build_message",
    "decode_message",
    "BaliseTelegram",
    "LoopMessage",
    "build_telegram",
    "decode_telegram",
    "MessageGenerator",
]

__version__ = "1.0.0"
