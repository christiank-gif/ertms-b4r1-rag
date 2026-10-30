"""Readable export formats for generated ETCS messages.

- JSON: fully decoded structure (header fields, packets with names and
  field values, plus raw hex and bit string).
- Text: human-readable line-by-line rendering.
"""

import json

from .messages import decode_message, TRAIN_TO_TRACK_MESSAGES, TRACK_TO_TRAIN_MESSAGES
from .telegram import decode_telegram, decode_loop
from .packets import packet_name
from .versions import decode_version_code


def message_to_dict(data: bytes) -> dict:
    msg = decode_message(data)
    return {
        "format": "ERTMS/ETCS Euroradio message (SUBSET-026-8)",
        "direction": "train_to_track (bord)" if msg.direction == "train_to_track"
                     else "track_to_train (sol)",
        "NID_MESSAGE": msg.nid_message,
        "title": msg.title,
        "fields": msg.fields,
        "packets": [
            {
                "NID_PACKET": p.number,
                "name": p.name,
                "fields": p.fields,
            }
            for p in msg.packets
        ],
        "hex": data.hex(),
        "length_bytes": len(data),
    }


def telegram_to_dict(data: bytes) -> dict:
    tg = decode_telegram(data)
    fields = dict(tg.fields)
    if "M_VERSION" in fields:
        try:
            fields["M_VERSION_text"] = str(decode_version_code(fields["M_VERSION"]))
        except ValueError:
            fields["M_VERSION_text"] = "invalid"
    return {
        "format": "ERTMS/ETCS Eurobalise telegram (SUBSET-026-8 §8.4.2)",
        "header_fields": fields,
        "packets": [
            {"NID_PACKET": p.number, "name": p.name, "fields": p.fields}
            for p in tg.packets
        ],
        "hex": data.hex(),
        "length_bytes": len(data),
    }


def loop_to_dict(data: bytes) -> dict:
    lm = decode_loop(data)
    return {
        "format": "ERTMS/ETCS Euroloop message (SUBSET-026-8 §8.4.3)",
        "header_fields": lm.fields,
        "packets": [
            {"NID_PACKET": p.number, "name": p.name, "fields": p.fields}
            for p in lm.packets
        ],
        "hex": data.hex(),
        "length_bytes": len(data),
    }


def export_json(data: bytes, kind="message") -> str:
    if kind == "telegram":
        obj = telegram_to_dict(data)
    elif kind == "loop":
        obj = loop_to_dict(data)
    else:
        obj = message_to_dict(data)
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def export_text(data: bytes, kind="message") -> str:
    obj = json.loads(export_json(data, kind))
    lines = [f"== {obj['format']} =="]
    if "direction" in obj:
        lines.append(f"Direction : {obj['direction']}")
        lines.append(f"NID_MESSAGE = {obj['NID_MESSAGE']} ({obj['title']})")
        for k, v in obj["fields"].items():
            lines.append(f"  {k} = {v}")
    else:
        for k, v in obj["header_fields"].items():
            lines.append(f"  {k} = {v}")
    lines.append("Packets:")
    for p in obj["packets"]:
        lines.append(f"  Packet {p['NID_PACKET']} ({p['name']}):")
        for k, v in p["fields"].items():
            lines.append(f"    {k} = {v}")
    lines.append(f"hex = {obj['hex']}")
    lines.append(f"length = {obj['length_bytes']} bytes")
    return "\n".join(lines)
