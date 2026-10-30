"""Command line interface to generate and decode ERTMS/ETCS messages.

Examples:
  python -m etcs_lang.cli gen sol msg3 --v-ema 80 --l-endsection 5000
  python -m etcs_lang.cli gen bord msg136 --d-lrbg 1200 --v-train 60
  python -m etcs_lang.cli gen sol telegram --packets 2,3
  python -m etcs_lang.cli decode 030a...
  python -m etcs_lang.cli list-messages
"""

import argparse
import json
import sys

from .generator import MessageGenerator
from .messages import TRAIN_TO_TRACK_MESSAGES, TRACK_TO_TRAIN_MESSAGES
from .versions import SystemVersion


def _hex(data: bytes) -> str:
    return data.hex()


def _parse_hex(s: str) -> bytes:
    return bytes.fromhex(s.strip())


def cmd_list(args):
    print("Train-to-track (bord -> sol):")
    for k in sorted(TRAIN_TO_TRACK_MESSAGES):
        print(f"  {k:>3}  {TRAIN_TO_TRACK_MESSAGES[k]}")
    print("Track-to-train (sol -> bord):")
    for k in sorted(TRACK_TO_TRAIN_MESSAGES):
        print(f"  {k:>3}  {TRACK_TO_TRAIN_MESSAGES[k]}")
    print("System versions (ch.6 §6.4):", ", ".join(str(v) for v in SystemVersion))


def cmd_gen(args):
    gen = MessageGenerator(args.direction, system_version=args.version,
                           nid_c=args.nid_c, nid_bg=args.nid_bg,
                           nid_engine=args.nid_engine)
    gen.set_time(args.t_train)
    name = args.message
    out = None
    if name == "msg155":
        out = gen.msg_155_initiate_session()
    elif name == "msg156":
        out = gen.msg_156_terminate_session()
    elif name == "msg159":
        out = gen.msg_159_session_established()
    elif name == "msg154":
        out = gen.msg_154_no_compatible_version()
    elif name == "msg146":
        out = gen.msg_146_acknowledgement()
    elif name == "msg136":
        out = gen.msg_136_position_report(args.d_lrbg, args.v_train, m_mode=args.mode,
                                          m_level=args.level, q_scale=args.q_scale)
    elif name == "msg129":
        out = gen.msg_129_validated_train_data({
            "nc_cdtrain": args.nc_cdtrain, "nc_train": args.nc_train,
            "l_train_m": args.l_train, "v_maxtrain_kmh": args.v_maxtrain,
            "m_loadinggauge": 1, "m_axleloadcat": 2, "m_airtight": 0,
            "n_axle": args.n_axle})
    elif name == "msg132":
        out = gen.msg_132_ma_request()
    elif name == "msg2":
        out = gen.msg_2_sr_authorisation(args.d_sr, m_ack=args.m_ack, q_scale=args.q_scale)
    elif name == "msg3":
        out = gen.msg_3_movement_authority({
            "q_scale": args.q_scale, "v_ema_kmh": args.v_ema, "t_ema_s": args.t_ema,
            "l_endsection_m": args.l_endsection, "sections_m": [],
            "q_dangerpoint": 1, "d_dp_m": args.d_dp, "v_releasedp_kmh": args.v_releasedp,
            "q_overlap": 0}, m_ack=args.m_ack)
    elif name == "msg16":
        out = gen.msg_16_unconditional_emergency_stop(m_ack=args.m_ack)
    elif name == "msg32":
        out = gen.msg_32_system_version(m_ack=args.m_ack)
    elif name == "msg38":
        out = gen.msg_38_ack_session_establishment(m_ack=args.m_ack)
    elif name == "msg41":
        out = gen.msg_41_train_accepted(args.t_train_of_155, m_ack=args.m_ack)
    elif name == "telegram":
        pkts = []
        for spec in (args.packets or []):
            num = int(spec)
            if num == 2:
                pkts.append(gen.packet_system_version_order())
            elif num == 3:
                pkts.append(gen.packet_national_values())
            else:
                raise SystemExit(f"packet {num} not supported in telegram shorthand")
        out = gen.balise_telegram(packets=pkts)
    else:
        raise SystemExit(f"unknown message {name}")
    result = {"message": name, "direction": args.direction, "hex": _hex(out),
              "bits": len(out) * 8, "bytes": list(out)}
    print(json.dumps(result, indent=1))


def cmd_decode(args):
    data = _parse_hex(args.data)
    if args.kind == "telegram":
        obj = MessageGenerator.decode_balise(data)
        print(json.dumps({"fields": obj.fields,
                          "packets": [{"number": p.number, "name": p.name, "fields": p.fields}
                                      for p in obj.packets]}, indent=1, default=str))
    elif args.kind == "loop":
        obj = MessageGenerator.decode_loop_msg(data)
        print(json.dumps({"fields": obj.fields,
                          "packets": [{"number": p.number, "name": p.name, "fields": p.fields}
                                      for p in obj.packets]}, indent=1, default=str))
    else:
        msg = MessageGenerator.decode(data)
        print(json.dumps({"id": msg.nid_message, "title": msg.title,
                          "direction": msg.direction, "fields": msg.fields,
                          "packets": [{"number": p.number, "name": p.name, "fields": p.fields}
                                      for p in msg.packets]}, indent=1, default=str))


def build_parser():
    p = argparse.ArgumentParser(prog="etcs-lang", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-messages", help="list radio messages and system versions").set_defaults(func=cmd_list)
    g = sub.add_parser("gen", help="generate a message/telegram")
    g.add_argument("direction", choices=["sol", "bord"])
    g.add_argument("message", help="msg2, msg3, msg16, msg32, msg38, msg41, msg129, msg132, msg136, msg146, msg154, msg155, msg156, msg159 or telegram")
    g.add_argument("--version", default="3.0", help="system version X.Y (ch.6)")
    g.add_argument("--nid-c", type=int, default=1)
    g.add_argument("--nid-bg", type=int, default=100)
    g.add_argument("--nid-engine", type=lambda x: int(x, 0), default=0x0012AB)
    g.add_argument("--t-train", type=int, default=0, help="T_TRAIN in 10 ms ticks")
    g.add_argument("--m-ack", type=int, default=0)
    g.add_argument("--q-scale", type=int, default=0)
    g.add_argument("--v-ema", type=float, default=80.0)
    g.add_argument("--t-ema", type=float, default=0.0)
    g.add_argument("--l-endsection", type=float, default=5000.0, help="metres")
    g.add_argument("--d-dp", type=float, default=100.0)
    g.add_argument("--v-releasedp", type=float, default=0.0)
    g.add_argument("--d-sr", type=float, default=2000.0)
    g.add_argument("--d-lrbg", type=float, default=1200.0)
    g.add_argument("--v-train", type=float, default=60.0)
    g.add_argument("--mode", type=int, default=0)
    g.add_argument("--level", type=int, default=2)
    g.add_argument("--nc-cdtrain", type=int, default=0)
    g.add_argument("--nc-train", type=int, default=0)
    g.add_argument("--l-train", type=float, default=200.0)
    g.add_argument("--v-maxtrain", type=float, default=160.0)
    g.add_argument("--n-axle", type=int, default=20)
    g.add_argument("--t-train-of-155", type=int, default=0)
    g.add_argument("--packets", type=lambda s: [int(x) for x in s.split(",")], default=None)
    g.set_defaults(func=cmd_gen)
    d = sub.add_parser("decode", help="decode hex message/telegram/loop")
    d.add_argument("data", help="hex string")
    d.add_argument("--kind", choices=["message", "telegram", "loop"], default="message")
    d.set_defaults(func=cmd_decode)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
