"""High-level generator for ERTMS/ETCS compliant track-to-train (sol) and
train-to-track (bord) messages, based on SUBSET-026 chapters 6, 7 and 8."""

from .versions import SystemVersion, parse_version, supported_envelope, is_legal_trackside
from .messages import (
    build_message, decode_message, RadioMessage,
    msg_2_sr_authorisation, msg_3_movement_authority, msg_32_system_version,
    msg_16_unconditional_emergency_stop, msg_38_ack_session_establishment,
    msg_41_train_accepted,
    msg_129_validated_train_data, msg_132_ma_request, msg_136_position_report,
    msg_146_acknowledgement, msg_154_no_compatible_version,
    msg_155_initiate_session, msg_156_terminate_session, msg_159_session_established,
)
from .packets import (
    build_packet_2_system_version_order, build_packet_2_onboard_versions,
    build_packet_3_national_values, build_packet_15_l2_ma, build_packet_21_gradient,
    build_packet_27_issp, build_packet_41_level_transition,
    build_packet_42_session_mgmt, build_packet_65_tsr, build_packet_0_vbcmk,
)
from .telegram import build_telegram, decode_telegram, build_loop_message, decode_loop


class MessageGenerator:
    """Factory for compliant ETCS messages.

    direction: 'sol' (track-to-train) or 'bord' (train-to-track).
    """

    def __init__(self, direction, system_version="3.0", nid_c=1, nid_bg=100,
                 nid_engine=0x0012AB, nid_rbc=1):
        if direction not in ("sol", "bord"):
            raise ValueError("direction must be 'sol' or 'bord'")
        self.direction = direction
        self.system_version = parse_version(system_version)
        if direction == "sol" and not is_legal_trackside(self.system_version):
            raise ValueError(f"{self.system_version} is not a legal trackside version (ch.6 §6.4.1)")
        self.nid_c = nid_c
        self.nid_bg = nid_bg
        self.nid_engine = nid_engine
        self.nid_rbc = nid_rbc
        self.nid_lrbg = (nid_c << 14) | nid_bg
        self.t_train = 0  # 10 ms ticks since 00:00:00 UTC, ch.7 §7.5.1.154

    def set_time(self, t_train_ticks: int):
        self.t_train = int(t_train_ticks)

    # ---- session management (ch.8 §8.6.13-8.6.17, §8.7.16-8.7.19) ----
    def msg_155_initiate_session(self) -> bytes:
        return msg_155_initiate_session(self.t_train, self.nid_engine)

    def msg_156_terminate_session(self) -> bytes:
        return msg_156_terminate_session(self.t_train, self.nid_engine)

    def msg_159_session_established(self) -> bytes:
        return msg_159_session_established(self.t_train, self.nid_engine)

    def msg_154_no_compatible_version(self) -> bytes:
        return msg_154_no_compatible_version(self.t_train, self.nid_engine)

    def msg_38_ack_session_establishment(self, m_ack=0) -> bytes:
        return msg_38_ack_session_establishment(self.t_train, m_ack, self.nid_lrbg)

    def msg_41_train_accepted(self, t_train_of_155, m_ack=0) -> bytes:
        return msg_41_train_accepted(self.t_train, m_ack, self.nid_lrbg, t_train_of_155)

    def msg_40_train_rejected(self, t_train_of_155, m_ack=0) -> bytes:
        return build_message(40, "track_to_train", self.t_train, m_ack=m_ack,
                             nid_lrbg=self.nid_lrbg, extra_fields={"T_TRAIN": int(t_train_of_155)})

    # ---- train data / position (bord) ----
    def msg_136_position_report(self, d_lrbg_m, v_train_kmh, m_mode=0, m_level=2,
                                q_scale=0, **kw) -> bytes:
        return msg_136_position_report(
            self.t_train, self.nid_engine, q_scale, self.nid_c, self.nid_bg,
            d_lrbg_m, v_train_kmh, m_mode, m_level, **kw)

    def msg_129_validated_train_data(self, train_data: dict) -> bytes:
        return msg_129_validated_train_data(self.t_train, self.nid_engine, train_data)

    def msg_132_ma_request(self) -> bytes:
        return msg_132_ma_request(self.t_train, self.nid_engine)

    def msg_146_acknowledgement(self) -> bytes:
        return msg_146_acknowledgement(self.t_train, self.nid_engine)

    # ---- movement authority / orders (sol) ----
    def msg_2_sr_authorisation(self, d_sr_m, m_ack=0, q_scale=0, extra_packets=None) -> bytes:
        return msg_2_sr_authorisation(self.t_train, m_ack, self.nid_lrbg, q_scale, d_sr_m,
                                      extra_packets=extra_packets)

    def msg_3_movement_authority(self, ma_params: dict, m_ack=0, extra_packets=None) -> bytes:
        return msg_3_movement_authority(self.t_train, m_ack, self.nid_lrbg, ma_params,
                                        extra_packets=extra_packets)

    def msg_16_unconditional_emergency_stop(self, m_ack=0) -> bytes:
        return msg_16_unconditional_emergency_stop(self.t_train, m_ack, self.nid_lrbg)

    def msg_32_system_version(self, m_version=None, m_ack=0) -> bytes:
        return msg_32_system_version(self.t_train, m_ack, self.nid_lrbg,
                                     m_version or self.system_version)

    # ---- packets (sol side) ----
    def packet_system_version_order(self, m_version=None, q_dir=0) -> bytes:
        return build_packet_2_system_version_order(m_version or self.system_version, q_dir)

    def packet_onboard_versions(self, versions=None) -> bytes:
        versions = versions or supported_envelope(self.system_version)
        return build_packet_2_onboard_versions(versions)

    def packet_national_values(self, d_validnv_m=100.0, values=None, q_scale=0) -> bytes:
        return build_packet_3_national_values(q_scale, d_validnv_m, self.nid_c, values or {})

    def packet_l2_ma(self, **ma_params) -> bytes:
        return build_packet_15_l2_ma(**ma_params)

    def packet_gradient(self, gradients, d_trackinit_m=0.0, q_scale=0) -> bytes:
        return build_packet_21_gradient(q_scale, d_trackinit_m, gradients)

    def packet_issp(self, profiles, d_trackinit_m=0.0, q_scale=0) -> bytes:
        return build_packet_27_issp(q_scale, d_trackinit_m, profiles)

    def packet_level_transition(self, m_leveltr, d_lrt_m, q_scale=0) -> bytes:
        return build_packet_41_level_transition(q_scale, m_leveltr, self.nid_c,
                                                self.nid_rbc, d_lrt_m)

    def packet_session_mgmt(self, q_rbc=1, nid_radio="49123456789012", q_sleepsession=0) -> bytes:
        return build_packet_42_session_mgmt(q_rbc, self.nid_c, self.nid_rbc, nid_radio,
                                            q_sleepsession)

    def packet_tsr(self, nid_tsr, d_tsr_m, l_tsr_m, v_tsr_kmh, q_scale=0) -> bytes:
        return build_packet_65_tsr(q_scale, nid_tsr, d_tsr_m, l_tsr_m, 1, v_tsr_kmh)

    def packet_vbc_marker(self, nid_vbcmk) -> bytes:
        return build_packet_0_vbcmk(nid_vbcmk)

    # ---- balise telegram / loop (sol) ----
    def balise_telegram(self, n_pig=0, n_total=1, m_mcount=0, packets=None, q_link=0,
                        m_version=None) -> bytes:
        return build_telegram(m_version or self.system_version, n_pig, n_total,
                              0, m_mcount, self.nid_c, self.nid_bg, q_link,
                              packets=packets)

    def loop_message(self, nid_loop=1, packets=None, m_version=None) -> bytes:
        return build_loop_message(m_version or self.system_version, self.nid_c, nid_loop,
                                  packets=packets)

    # ---- decoding helpers ----
    @staticmethod
    def decode(data: bytes) -> RadioMessage:
        return decode_message(data)

    @staticmethod
    def decode_balise(data: bytes):
        return decode_telegram(data)

    @staticmethod
    def decode_loop_msg(data: bytes):
        return decode_loop(data)
