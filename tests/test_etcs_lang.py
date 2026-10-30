"""Tests for the ERTMS/ETCS language toolkit (SUBSET-026 ch.6/7/8)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etcs_lang.bitstream import BitWriter, BitReader
from etcs_lang.versions import (
    SystemVersion, version_code, parse_version, decode_version_code,
    is_legal_trackside, supported_envelope,
)
from etcs_lang.packets import (
    build_packet_15_l2_ma, build_packet_42_session_mgmt, build_packet_0_position_report,
    build_packet_2_system_version_order, build_packet_2_onboard_versions,
    build_packet_255, decode_packet, build_packet_11_train_data,
    build_packet_5_train_running_number,
)
from etcs_lang.messages import (
    build_message, decode_message, msg_3_movement_authority, msg_136_position_report,
    msg_155_initiate_session, msg_32_system_version,
)
from etcs_lang.telegram import build_telegram, decode_telegram, build_loop_message, decode_loop
from etcs_lang.generator import MessageGenerator
from etcs_lang.bitstream import BitReader as BR


def bits_of(data: bytes):
    return BR(data)


class TestBitstream(unittest.TestCase):
    def test_roundtrip(self):
        w = BitWriter()
        w.write_uint(0b101, 3)
        w.write_uint(255, 8)
        w.write_uint(1, 1)
        r = BitReader(w.to_bytes(pad=True))
        self.assertEqual(r.read_uint(3), 0b101)
        self.assertEqual(r.read_uint(8), 255)
        self.assertEqual(r.read_uint(1), 1)

    def test_range_check(self):
        w = BitWriter()
        with self.assertRaises(ValueError):
            w.write_uint(8, 3)


class TestVersions(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(version_code("1.0"), 0b0010000)
        self.assertEqual(version_code("1.1"), 0b0010001)
        self.assertEqual(version_code("2.0"), 0b0100000)
        self.assertEqual(version_code("2.2"), 0b0100010)
        self.assertEqual(version_code("3.0"), 0b0110000)

    def test_decode(self):
        self.assertEqual(decode_version_code(0b0110000), SystemVersion.V3_0)

    def test_legal_trackside(self):
        self.assertTrue(is_legal_trackside("3.0"))
        self.assertTrue(is_legal_trackside("1.1"))
        with self.assertRaises(ValueError):
            is_legal_trackside("4.0")

    def test_envelope(self):
        env = supported_envelope("2.1")
        self.assertEqual(env[0], SystemVersion.V1_0)
        self.assertEqual(env[-1], SystemVersion.V2_1)


class TestPackets(unittest.TestCase):
    def test_packet_255(self):
        self.assertEqual(build_packet_255(), b"\xff")

    def test_packet_2_t2t_lpacket(self):
        data = build_packet_2_system_version_order("3.0")
        r = BR(data)
        self.assertEqual(r.read_uint(8), 2)       # NID_PACKET
        self.assertEqual(r.read_uint(2), 0)       # Q_DIR
        l_packet = r.read_uint(13)
        self.assertEqual(l_packet, 32)  # 30 bits of content, padded to 4 bytes; L_PACKET counts the padded packet
        self.assertEqual(r.read_uint(7), 0b0110000)  # M_VERSION 3.0

    def test_packet_15_roundtrip(self):
        data = build_packet_15_l2_ma(q_scale=1, v_ema_kmh=80, t_ema_s=60,
                                     l_endsection_m=5000, sections_m=[1000],
                                     q_dangerpoint=1, d_dp_m=200, v_releasedp_kmh=30,
                                     q_overlap=1, d_startol_m=100, t_ol_s=30,
                                     d_ol_m=50, v_releaseol_kmh=40)
        r = BR(data)
        pkt = decode_packet(r, "track_to_train")
        self.assertEqual(pkt.number, 15)
        self.assertEqual(pkt.fields["V_EMA"], 16)   # 80/5
        self.assertEqual(pkt.fields["T_EMA"], 60)
        self.assertEqual(pkt.fields["sections"][0]["L_SECTION"], 1000)
        self.assertEqual(pkt.fields["L_ENDSECTION"], 5000)  # q_scale=1 -> 1 m
        self.assertEqual(pkt.fields["D_DP"], 200)
        self.assertEqual(pkt.fields["V_RELEASEDP"], 6)
        self.assertEqual(pkt.fields["Q_OVERLAP"], 1)
        self.assertEqual(pkt.fields["V_RELEASEOL"], 8)

    def test_packet_42(self):
        data = build_packet_42_session_mgmt(1, 1, 5, "49228765432")
        r = BR(data)
        pkt = decode_packet(r, "track_to_train")
        self.assertEqual(pkt.number, 42)
        self.assertEqual(pkt.fields["NID_C"], 1)
        self.assertEqual(pkt.fields["NID_RBC"], 5)

    def test_packet_0_train_position(self):
        data = build_packet_0_position_report(q_scale=0, nid_c=1, nid_bg=100,
                                              d_lrbg_m=12.0, q_dirlrbg=0, q_dlrbg=0,
                                              l_doubtover_m=0, l_doubtunder_m=0,
                                              q_integrity=0, v_train_kmh=60,
                                              q_dirtrain=0, m_mode=0, m_level=2)
        r = BR(data)
        pkt = decode_packet(r, "train_to_track")
        self.assertEqual(pkt.number, 0)
        self.assertEqual(pkt.fields["NID_C"], 1)
        self.assertEqual(pkt.fields["NID_BG"], 100)
        self.assertEqual(pkt.fields["D_LRBG"], 120)  # 12 m / 0.10
        self.assertEqual(pkt.fields["V_TRAIN"], 12)  # 60/5
        self.assertEqual(pkt.fields["M_LEVEL"], 2)

    def test_packet_2_onboard_versions(self):
        data = build_packet_2_onboard_versions(["1.0", "1.1", "2.0", "2.1", "2.2", "3.0"])
        r = BR(data)
        self.assertEqual(r.read_uint(8), 2)
        l_packet = r.read_uint(13)
        self.assertEqual(l_packet, len(data) * 8)
        self.assertEqual(r.read_uint(7), 0b0010000)
        self.assertEqual(r.read_uint(5), 5)


class TestMessages(unittest.TestCase):
    def test_msg155_structure(self):
        data = msg_155_initiate_session(t_train=123456, nid_engine=0x0012AB)
        r = BR(data)
        self.assertEqual(r.read_uint(8), 155)
        l_message = r.read_uint(10)
        self.assertEqual(l_message, len(data))  # bytes, header included
        self.assertEqual(r.read_uint(32), 123456)
        self.assertEqual(r.read_uint(24), 0x0012AB)

    def test_msg3_roundtrip(self):
        ma = {"q_scale": 1, "v_ema_kmh": 120, "t_ema_s": 0, "l_endsection_m": 10000,
              "sections_m": [], "q_dangerpoint": 0, "d_dp_m": 0, "v_releasedp_kmh": 0,
              "q_overlap": 0}
        data = msg_3_movement_authority(t_train=42, m_ack=1, nid_lrbg=(1 << 14) | 100,
                                        ma_params=ma)
        msg = decode_message(data)
        self.assertEqual(msg.nid_message, 3)
        self.assertEqual(msg.direction, "track_to_train")
        self.assertEqual(msg.fields["T_TRAIN"], 42)
        self.assertEqual(msg.fields["M_ACK"], 1)
        self.assertEqual(msg.fields["NID_LRBG"], (1 << 14) | 100)
        self.assertEqual(len(msg.packets), 1)
        self.assertEqual(msg.packets[0].number, 15)
        self.assertEqual(msg.packets[0].fields["V_EMA"], 24)

    def test_msg136_roundtrip(self):
        data = msg_136_position_report(t_train=7, nid_engine=0xABCDEF, q_scale=0,
                                       nid_c=1, nid_bg=5, d_lrbg_m=25.0,
                                       v_train_kmh=100, m_mode=0, m_level=2)
        msg = decode_message(data)
        self.assertEqual(msg.nid_message, 136)
        self.assertEqual(msg.direction, "train_to_track")
        self.assertEqual(msg.fields["NID_ENGINE"], 0xABCDEF)
        self.assertEqual(msg.packets[0].number, 0)
        self.assertEqual(msg.packets[0].fields["D_LRBG"], 250)

    def test_msg32_version(self):
        data = msg_32_system_version(t_train=1, m_ack=0, nid_lrbg=0, m_version="2.2")
        msg = decode_message(data)
        self.assertEqual(msg.nid_message, 32)


class TestTelegram(unittest.TestCase):
    def test_balise_telegram_header_50_bits(self):
        pkt2 = build_packet_2_system_version_order("3.0")
        data = build_telegram("3.0", n_pig=0, n_total=1, m_dup=0, m_mcount=3,
                              nid_c=1, nid_bg=100, packets=[pkt2])
        tg = decode_telegram(data)
        self.assertEqual(tg.fields["M_VERSION"], 0b0110000)
        self.assertEqual(tg.fields["N_PIG"], 0)
        self.assertEqual(tg.fields["N_TOTAL"], 1)
        self.assertEqual(tg.fields["M_MCOUNT"], 3)
        self.assertEqual(tg.fields["NID_C"], 1)
        self.assertEqual(tg.fields["NID_BG"], 100)
        self.assertEqual(tg.fields["Q_LINK"], 0)
        self.assertEqual([p.number for p in tg.packets], [2])

    def test_loop_message_header_33_bits(self):
        pkt2 = build_packet_2_system_version_order("2.2")
        data = build_loop_message("2.2", nid_c=1, nid_loop=7, packets=[pkt2])
        lm = decode_loop(data)
        self.assertEqual(lm.fields["M_VERSION"], 0b0100010)
        self.assertEqual(lm.fields["Q_MEDIA"], 1)
        self.assertEqual(lm.fields["NID_LOOP"], 7)
        self.assertEqual([p.number for p in lm.packets], [2])


class TestGenerator(unittest.TestCase):
    def test_sol_and_bord(self):
        sol = MessageGenerator("sol", system_version="3.0")
        bord = MessageGenerator("bord", system_version="3.0")
        m = sol.msg_3_movement_authority(
            {"q_scale": 1, "v_ema_kmh": 100, "t_ema_s": 0, "l_endsection_m": 3000,
             "sections_m": [], "q_dangerpoint": 0, "d_dp_m": 0,
             "v_releasedp_kmh": 0, "q_overlap": 0})
        dec = MessageGenerator.decode(m)
        self.assertEqual(dec.nid_message, 3)
        m2 = bord.msg_155_initiate_session()
        dec2 = MessageGenerator.decode(m2)
        self.assertEqual(dec2.nid_message, 155)

    def test_illegal_trackside_version_rejected(self):
        with self.assertRaises(ValueError):
            MessageGenerator("sol", system_version="4.0")


if __name__ == "__main__":
    unittest.main()


class TestRules(unittest.TestCase):
    def test_allowed_packets(self):
        from etcs_lang.rules import allowed_packets
        mand, opt = allowed_packets(3, "track_to_train")
        self.assertIn(15, mand)
        self.assertIn(21, opt)
        mand, opt = allowed_packets(136, "train_to_track")
        self.assertIn(0, mand)
        self.assertIn(44, opt)
        mand, opt = allowed_packets(155, "train_to_track")
        self.assertEqual(mand, [])

    def test_validate(self):
        from etcs_lang.rules import validate_message
        self.assertEqual(validate_message(3, "track_to_train", [15, 21]), [])
        self.assertTrue(validate_message(3, "track_to_train", [21]))          # missing 15
        self.assertTrue(validate_message(136, "train_to_track", [0, 9]))      # 9 not allowed
        self.assertTrue(validate_message(3, "track_to_train", [15, 15]))      # duplicate
        self.assertEqual(validate_message(155, "train_to_track", []), [])


class TestExporter(unittest.TestCase):
    def test_export_roundtrip(self):
        import json as _json
        from etcs_lang.exporter import export_json, export_text
        from etcs_lang.messages import msg_3_movement_authority
        ma = {"q_scale": 1, "v_ema_kmh": 120, "t_ema_s": 0, "l_endsection_m": 10000,
              "sections_m": [], "q_dangerpoint": 0, "d_dp_m": 0,
              "v_releasedp_kmh": 0, "q_overlap": 0}
        data = msg_3_movement_authority(42, 1, (1 << 14) | 100, ma)
        obj = _json.loads(export_json(data, "message"))
        self.assertEqual(obj["NID_MESSAGE"], 3)
        self.assertEqual(obj["packets"][0]["NID_PACKET"], 15)
        self.assertIn("hex", obj)
        txt = export_text(data, "message")
        self.assertIn("Movement Authority", txt)
        self.assertIn("Packet 15", txt)

    def test_webui_api(self):
        import json as _json
        from etcs_lang.webui import Api
        api = Api()
        self.assertEqual(len(api.messages("sol")), 24)
        r = api.generate(_json.dumps({"direction": "sol", "nid": 3, "version": "3.0",
                                      "nid_c": 1, "nid_bg": 100, "packets": [15],
                                      "m_ack": 1, "v_ema": 100, "l_endsection": 8000,
                                      "d_dp": 100, "q_scale": 1}))
        self.assertTrue(r["hex"].startswith("03"))
        self.assertEqual(api.validate(3, "sol", [15]), [])
