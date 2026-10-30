"""Local web GUI to build ERTMS/ETCS messages, step by step.

Run with:  python -m etcs_lang.webui
A local HTTP server (standard library only) starts on 127.0.0.1 and your
default browser opens automatically. No external dependency, works on any
machine with a modern browser.

Flow:
  Step 1: Eurobalise telegram OR Euroradio message (no Euroloop).
  Step 2 (telegram): configure the 50-bit balise header (ch.8 §8.4.2.1),
     pick packets, set N_TOTAL -> one telegram per balise is generated.
  Step 2 (radio): pick direction (sol->bord / bord->sol, ch.8 §8.5/§8.6/§8.7),
     pick a message, pick allowed packets (§8.4.4.4), generate.
  Step 3: decoded view + download as readable JSON or TXT.
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from .generator import MessageGenerator
from .messages import TRAIN_TO_TRACK_MESSAGES, TRACK_TO_TRAIN_MESSAGES, build_message
from .packets import (
    packet_name, packet_fields, build_packet_from_fields, build_packet_0_vbcmk,
)
from .telegram import build_telegram
from .rules import allowed_packets, validate_message
from .exporter import export_json, export_text

BALISE_PACKET_BUILDERS = {
    0: lambda g, p: build_packet_0_vbcmk(int(p.get("nid_vbcmk", 0))),
    2: lambda g, p: build_packet_2_system_version_order(p.get("version", str(g.system_version))),
    3: lambda g, p: build_packet_3_national_values(int(p.get("q_scale", 0)), float(p.get("d_validnv", 100)),
                                                    g.nid_c, {}),
    15: lambda g, p: build_packet_15_l2_ma(
        q_scale=int(p.get("q_scale", 0)), v_ema_kmh=float(p.get("v_ema", 80)),
        t_ema_s=float(p.get("t_ema", 0)), l_endsection_m=float(p.get("l_endsection", 5000)),
        sections_m=[], q_dangerpoint=1, d_dp_m=float(p.get("d_dp", 100)),
        v_releasedp_kmh=float(p.get("v_releasedp", 0)), q_overlap=0),
    21: lambda g, p: build_packet_21_gradient(int(p.get("q_scale", 0)), 0.0, [(-5, 1000)]),
    27: lambda g, p: build_packet_27_issp(int(p.get("q_scale", 0)), 0.0, [(80, 2000, 0)]),
    41: lambda g, p: build_packet_41_level_transition(int(p.get("q_scale", 0)), 2, g.nid_c, 1, 0.0),
    42: lambda g, p: build_packet_42_session_mgmt(1, g.nid_c, 1, "49228765432"),
    44: lambda g, p: build_packet_44_external_data(1, b"\\x01\\x02\\x03"),
    65: lambda g, p: build_packet_65_tsr(int(p.get("q_scale", 0)), int(p.get("nid_tsr", 1)),
                                         500, 200, 1, 60),
    136: lambda g, p: build_packet_136_infill_location(0, g.nid_c, g.nid_bg),
}


def radio_generate(p):
    direction = p["direction"]
    nid = int(p["nid"])
    gen = MessageGenerator(direction, system_version=p.get("version", "3.0"),
                           nid_c=int(p.get("nid_c", 1)), nid_bg=int(p.get("nid_bg", 100)))
    gen.set_time(int(p.get("t_train", 0)))
    q = lambda k, d=0.0: float(p.get(k, d))
    pkts = [int(x) for x in p.get("packets", [])]
    extra = []
    if direction == "sol":
        if 2 in pkts:
            extra.append(gen.packet_system_version_order())
        if 3 in pkts:
            extra.append(gen.packet_national_values())
        if 42 in pkts:
            extra.append(gen.packet_session_mgmt())
        if 65 in pkts:
            extra.append(gen.packet_tsr(1, 500, 200, 60, q("q_scale")))
        if 136 in pkts:
            extra.append(build_packet_136_infill_location(0, gen.nid_c, gen.nid_bg))
        if nid == 3:
            ma = {"q_scale": int(q("q_scale")), "v_ema_kmh": q("v_ema"),
                  "t_ema_s": q("t_ema"), "l_endsection_m": q("l_endsection"),
                  "sections_m": [], "q_dangerpoint": 1, "d_dp_m": q("d_dp"),
                  "v_releasedp_kmh": q("v_releasedp"), "q_overlap": 0}
            data = gen.msg_3_movement_authority(ma, m_ack=int(q("m_ack")), extra_packets=extra)
        elif nid == 2:
            data = gen.msg_2_sr_authorisation(q("d_sr"), m_ack=int(q("m_ack")),
                                              q_scale=int(q("q_scale")), extra_packets=extra)
        elif nid == 32:
            data = gen.msg_32_system_version(m_version=p.get("version", "3.0"),
                                             m_ack=int(q("m_ack")))
        elif nid == 16:
            data = gen.msg_16_unconditional_emergency_stop(m_ack=int(q("m_ack")))
        elif nid == 38:
            data = gen.msg_38_ack_session_establishment(m_ack=int(q("m_ack")))
        elif nid == 41:
            data = gen.msg_41_train_accepted(int(p.get("t_train", 0)), m_ack=int(q("m_ack")))
        elif nid == 40:
            data = gen.msg_40_train_rejected(int(p.get("t_train", 0)), m_ack=int(q("m_ack")))
        else:
            data = build_message(nid, "track_to_train", gen.t_train,
                                 m_ack=int(q("m_ack")), nid_lrbg=gen.nid_lrbg, packets=extra)
    else:
        if nid == 136:
            data = gen.msg_136_position_report(
                q("d_lrbg"), q("v_train"), m_mode=int(q("m_mode")),
                m_level=int(q("m_level")), q_scale=int(q("q_scale")))
        elif nid == 129:
            data = gen.msg_129_validated_train_data({
                "nc_cdtrain": 0, "nc_train": 0, "l_train_m": q("l_train"),
                "v_maxtrain_kmh": q("v_maxtrain"), "m_loadinggauge": 1,
                "m_axleloadcat": 2, "m_airtight": 0, "n_axle": int(q("n_axle"))})
        elif nid == 155:
            data = gen.msg_155_initiate_session()
        elif nid == 156:
            data = gen.msg_156_terminate_session()
        elif nid == 159:
            data = gen.msg_159_session_established()
        elif nid == 154:
            data = gen.msg_154_no_compatible_version()
        elif nid == 146:
            data = gen.msg_146_acknowledgement()
        elif nid == 132:
            data = gen.msg_132_ma_request()
        else:
            data = build_message(nid, "train_to_track", gen.t_train, nid_engine=gen.nid_engine)
    return {"hex": data.hex(), "json": export_json(data, "message"), "text": export_text(data, "message")}


def telegram_generate(p):
    """p['packets'] = list of {'num': n, 'values': {...}} built by the user."""
    version = p.get("version", "3.0")
    nid_c = int(p.get("nid_c", 1))
    nid_bg = int(p.get("nid_bg", 100))
    n_total = max(1, min(8, int(p.get("n_total", 1))))
    pkts = []
    for spec in p.get("packets", []):
        num = int(spec["num"])
        values = dict(spec.get("values", {}))
        values.setdefault("Q_DIR", 0)
        if num == 2 and "M_VERSION" not in values:
            values["M_VERSION"] = version
        if num == 0:
            pkts.append(build_packet_0_vbcmk(int(values.get("NID_VBCMK", 0))))  # first (§8.4.2.3)
        else:
            pkts.append(build_packet_from_fields(num, "track_to_train", values))
    def _is_pkt0(b):
        bits = b if isinstance(b, list) else None
        if bits is None:
            from .bitstream import BitReader
            bits = BitReader(b).to_bits()
        return bits[:8] == [0]*8
    pkts.sort(key=lambda b: 0 if _is_pkt0(b) else 1)  # packet 0 first (§8.4.2.3)
    telegrams = []
    for n_pig in range(n_total):
        data = build_telegram(version, n_pig=n_pig, n_total=n_total,
                              m_dup=int(p.get("m_dup", 0)), m_mcount=int(p.get("m_mcount", 0)),
                              nid_c=nid_c, nid_bg=nid_bg, q_link=int(p.get("q_link", 0)),
                              q_updown=int(p.get("q_updown", 1)), packets=pkts)
        telegrams.append({"n_pig": n_pig, "hex": data.hex(),
                          "json": export_json(data, "telegram"),
                          "text": export_text(data, "telegram")})
    return {"n_total": n_total, "telegrams": telegrams}


def api_route(path, body):
    if path == "/api/messages":
        table = TRACK_TO_TRAIN_MESSAGES if body.get("direction") == "sol" else TRAIN_TO_TRACK_MESSAGES
        return [{"id": nid, "title": t} for nid, t in sorted(table.items())]
    if path == "/api/packets":
        d = "track_to_train" if body.get("direction") == "sol" else "train_to_track"
        mandatory, optional = allowed_packets(int(body["nid"]), d)
        lab = lambda p: {"num": p, "name": packet_name(p, d)}
        return {"mandatory": [lab(p) for p in mandatory], "optional": [lab(p) for p in optional]}
    if path == "/api/balise_packets":
        from .packets import PACKET_DEFS
        nums = sorted({int(k.split("#")[0]) for k, v in PACKET_DEFS.items()
                       if v["direction"] == "track_to_train" and k.split("#")[0].isdigit()})
        return [{"num": n, "name": packet_name(n, "track_to_train")} for n in nums]
    if path == "/api/packet_fields":
        num = int(body["num"])
        d = body.get("direction", "track_to_train")
        fields = packet_fields(num, d)
        return {"num": num, "name": packet_name(num, d),
                "fields": [{"name": f["name"], "bits": f["length_bits"],
                            "repeat": f["repeat"], "comment": f.get("comment", "")}
                           for f in fields
                           if f["name"] not in ("NID_PACKET", "L_PACKET", "Q_DIR")]}
    if path == "/api/validate":
        d = "track_to_train" if body.get("direction") == "sol" else "train_to_track"
        return validate_message(int(body["nid"]), d, [int(x) for x in body.get("packets", [])])
    if path == "/api/generate":
        return radio_generate(body)
    if path == "/api/generate_telegram":
        return telegram_generate(body)
    raise KeyError(path)


HTML = open(__file__.replace("webui.py", "webui.html"), encoding="utf-8").read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, content, ctype="application/json; charset=utf-8"):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, HTML, "text/html; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            self._send(200, json.dumps(api_route(self.path, body), ensure_ascii=False, default=str))
        except Exception as exc:
            self._send(500, json.dumps({"error": str(exc)}))


def main(port=8765):
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Interface ouverte dans le navigateur : {url}  (Ctrl+C pour arreter)")
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
