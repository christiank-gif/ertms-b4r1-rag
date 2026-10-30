"""Graphical interface to build ERTMS/ETCS bord/sol messages.

Run with:  python -m etcs_lang.gui

Only messages and packets allowed by SUBSET-026-8 (ch.8 §8.4.4.4, §8.6, §8.7)
are selectable. Generated messages can be saved in readable formats
(JSON decoded + hex, or plain text) and re-opened for decoding.
"""

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from .generator import MessageGenerator
from .messages import TRAIN_TO_TRACK_MESSAGES, TRACK_TO_TRAIN_MESSAGES
from .packets import packet_name
from .rules import allowed_packets, validate_message
from .exporter import export_json, export_text

PACKET_LABELS_T2T = {  # selectable packets with builders, track-to-train
    2: "System Version order", 3: "National Values", 15: "Level 2 MA",
    21: "Gradient Profile", 27: "ISSP", 41: "Level Transition Order",
    42: "Session Management (GSM-R)", 65: "Temporary Speed Restriction",
    136: "Infill Location Reference",
}
PACKET_LABELS_T2Tr = {  # train-to-track
    0: "Position Report", 4: "Error Reporting", 5: "Train Running Number",
    11: "Validated Train Data",
}


class EtcsGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ERTMS/ETCS B4R1 - Générateur de messages bord/sol (SUBSET-026 ch.6/7/8)")
        self.geometry("980x720")
        self.gen = None
        self.current_packets = []
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)

        ttk.Label(top, text="Direction :").grid(row=0, column=0, sticky="w")
        self.direction = tk.StringVar(value="sol")
        ttk.Radiobutton(top, text="Sol → Bord (track-to-train)", variable=self.direction,
                        value="sol", command=self._on_direction).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(top, text="Bord → Sol (train-to-track)", variable=self.direction,
                        value="bord", command=self._on_direction).grid(row=0, column=2, sticky="w")

        ttk.Label(top, text="Version système :").grid(row=1, column=0, sticky="w")
        self.version = tk.StringVar(value="3.0")
        ttk.Combobox(top, textvariable=self.version, width=6,
                     values=["1.0", "1.1", "2.0", "2.1", "2.2", "2.3", "3.0"]).grid(row=1, column=1, sticky="w")
        ttk.Label(top, text="NID_C :").grid(row=1, column=2, sticky="w")
        self.nid_c = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=0, to=1023, textvariable=self.nid_c, width=6).grid(row=1, column=3, sticky="w")
        ttk.Label(top, text="NID_BG :").grid(row=1, column=4, sticky="w")
        self.nid_bg = tk.IntVar(value=100)
        ttk.Spinbox(top, from_=0, to=16382, textvariable=self.nid_bg, width=8).grid(row=1, column=5, sticky="w")
        ttk.Label(top, text="T_TRAIN (ticks 10 ms) :").grid(row=2, column=0, sticky="w")
        self.t_train = tk.IntVar(value=0)
        ttk.Entry(top, textvariable=self.t_train, width=12).grid(row=2, column=1, sticky="w")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=6)
        ttk.Label(mid, text="Message :").grid(row=0, column=0, sticky="nw")
        self.msg_list = tk.Listbox(mid, height=12, exportselection=False)
        self.msg_list.grid(row=1, column=0, sticky="nsew")
        self.msg_list.bind("<<ListboxSelect>>", self._on_message_select)
        sb = ttk.Scrollbar(mid, command=self.msg_list.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.msg_list.config(yscrollcommand=sb.set)

        right = ttk.Frame(mid)
        right.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=8)
        ttk.Label(right, text="Paquets autorisés (ch.8) :").pack(anchor="w")
        self.packet_frame = ttk.Frame(right)
        self.packet_frame.pack(anchor="w", fill="x")
        self.packet_vars = {}

        params = ttk.LabelFrame(self, text="Paramètres du message")
        params.pack(fill="x", padx=6, pady=4)
        self.param_entries = {}
        self._build_params(params)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=6, pady=4)
        ttk.Button(btns, text="Générer le message", command=self._generate).pack(side="left")
        ttk.Button(btns, text="Valider conformité (ch.8)", command=self._validate).pack(side="left", padx=4)
        ttk.Button(btns, text="Enregistrer JSON…", command=lambda: self._save("json")).pack(side="left", padx=4)
        ttk.Button(btns, text="Enregistrer TXT…", command=lambda: self._save("txt")).pack(side="left", padx=4)
        ttk.Button(btns, text="Décoder un fichier…", command=self._open_decode).pack(side="left", padx=4)

        self.out = scrolledtext.ScrolledText(self, height=16, wrap="none")
        self.out.pack(fill="both", expand=True, padx=6, pady=4)

        self._on_direction()

    def _build_params(self, parent):
        fields = [
            ("m_ack", "M_ACK (0/1)", "0"),
            ("v_ema", "V_EMA (km/h)", "80"),
            ("t_ema", "T_EMA (s)", "0"),
            ("l_endsection", "L_ENDSECTION (m)", "5000"),
            ("d_dp", "D_DP (m)", "100"),
            ("v_releasedp", "V_RELEASEDP (km/h)", "0"),
            ("d_sr", "D_SR (m)", "2000"),
            ("q_scale", "Q_SCALE (0/1/2)", "0"),
            ("d_lrbg", "D_LRBG (m)", "1200"),
            ("v_train", "V_TRAIN (km/h)", "60"),
            ("m_mode", "M_MODE", "0"),
            ("m_level", "M_LEVEL", "2"),
            ("l_train", "L_TRAIN (m)", "200"),
            ("v_maxtrain", "V_MAXTRAIN (km/h)", "160"),
            ("n_axle", "N_AXLE", "20"),
        ]
        for i, (key, label, default) in enumerate(fields):
            ttk.Label(parent, text=label).grid(row=i // 4, column=(i % 4) * 2, sticky="w", padx=2)
            var = tk.StringVar(value=default)
            ttk.Entry(parent, textvariable=var, width=10).grid(row=i // 4, column=(i % 4) * 2 + 1, sticky="w", padx=2)
            self.param_entries[key] = var

    def _p(self, key):
        try:
            return float(self.param_entries[key].get())
        except ValueError:
            return 0.0

    def _on_direction(self):
        self.msg_list.delete(0, "end")
        table = TRACK_TO_TRAIN_MESSAGES if self.direction.get() == "sol" else TRAIN_TO_TRACK_MESSAGES
        for nid in sorted(table):
            self.msg_list.insert("end", f"{nid} - {table[nid]}")
        for w in self.packet_frame.winfo_children():
            w.destroy()
        self.packet_vars.clear()
        self.current_packets = []

    def _on_message_select(self, _evt):
        sel = self.msg_list.curselection()
        if not sel:
            return
        nid = int(self.msg_list.get(sel[0]).split(" - ")[0])
        direction = "track_to_train" if self.direction.get() == "sol" else "train_to_track"
        mandatory, optional = allowed_packets(nid, direction)
        for w in self.packet_frame.winfo_children():
            w.destroy()
        self.packet_vars.clear()
        labels = PACKET_LABELS_T2T if direction == "track_to_train" else PACKET_LABELS_T2Tr
        all_allowed = mandatory + [p for p in optional if p in labels]
        ttk.Label(self.packet_frame, text=f"Obligatoires: {mandatory or 'aucun'}").pack(anchor="w")
        for p in all_allowed:
            var = tk.IntVar(value=1 if p in mandatory else 0)
            cb = ttk.Checkbutton(self.packet_frame, text=f"Paquet {p} - {labels.get(p, packet_name(p, direction))}",
                                 variable=var, state="normal" if p not in mandatory else "disabled")
            cb.pack(anchor="w")
            self.packet_vars[p] = var
        self.current_nid = nid

    def _selected_packets(self):
        return [p for p, v in self.packet_vars.items() if v.get() == 1]

    def _make_gen(self):
        return MessageGenerator(self.direction.get(), system_version=self.version.get(),
                                nid_c=self.nid_c.get(), nid_bg=self.nid_bg.get())

    def _build_packets(self, gen, direction):
        pkts = []
        for p in self._selected_packets():
            if direction == "sol":
                if p == 2:
                    pkts.append(gen.packet_system_version_order())
                elif p == 3:
                    pkts.append(gen.packet_national_values())
                elif p == 15:
                    pkts.append(gen.packet_l2_ma(q_scale=int(self._p("q_scale")),
                                                  v_ema_kmh=self._p("v_ema"),
                                                  t_ema_s=self._p("t_ema"),
                                                  l_endsection_m=self._p("l_endsection"),
                                                  q_dangerpoint=1, d_dp_m=self._p("d_dp"),
                                                  v_releasedp_kmh=self._p("v_releasedp"),
                                                  q_overlap=0))
                elif p == 42:
                    pkts.append(gen.packet_session_mgmt())
                elif p == 65:
                    pkts.append(gen.packet_tsr(nid_tsr=1, d_tsr_m=500, l_tsr_m=200,
                                               v_tsr_kmh=60, q_scale=int(self._p("q_scale"))))
                elif p == 136:
                    from .packets import build_packet_136_infill_location
                    pkts.append(build_packet_136_infill_location(0, self.nid_c.get(), self.nid_bg.get()))
            else:
                if p == 0:
                    from .messages import msg_136_position_report
                elif p == 11:
                    from .packets import build_packet_11_train_data
                    pkts.append(build_packet_11_train_data(
                        nc_cdtrain=0, nc_train=0, l_train_m=self._p("l_train"),
                        v_maxtrain_kmh=self._p("v_maxtrain"), m_loadinggauge=1,
                        m_axleloadcat=2, m_airtight=0, n_axle=int(self._p("n_axle"))))
                elif p == 5:
                    from .packets import build_packet_5_train_running_number
                    pkts.append(build_packet_5_train_running_number("12345678"))
                elif p == 4:
                    from .packets import build_packet_4_error_reporting
                    pkts.append(build_packet_4_error_reporting(0))
        return pkts

    def _generate(self):
        gen = self._make_gen()
        gen.set_time(self.t_train.get())
        nid = getattr(self, "current_nid", None)
        if nid is None:
            messagebox.showwarning("Message", "Sélectionnez d'abord un message.")
            return
        direction = "sol" if self.direction.get() == "sol" else "bord"
        pkts = self._build_packets(gen, direction)
        extra = None
        try:
            if nid == 3:
                data = gen.msg_3_movement_authority(
                    {"q_scale": int(self._p("q_scale")), "v_ema_kmh": self._p("v_ema"),
                     "t_ema_s": self._p("t_ema"), "l_endsection_m": self._p("l_endsection"),
                     "sections_m": [], "q_dangerpoint": 1, "d_dp_m": self._p("d_dp"),
                     "v_releasedp_kmh": self._p("v_releasedp"), "q_overlap": 0},
                    m_ack=int(self._p("m_ack")), extra_packets=pkts if 15 not in self._selected_packets() else None)
            elif nid == 2:
                data = gen.msg_2_sr_authorisation(self._p("d_sr"), m_ack=int(self._p("m_ack")),
                                                  q_scale=int(self._p("q_scale")), extra_packets=pkts)
            elif nid == 136:
                data = gen.msg_136_position_report(
                    self._p("d_lrbg"), self._p("v_train"), m_mode=int(self._p("m_mode")),
                    m_level=int(self._p("m_level")), q_scale=int(self._p("q_scale")),
                    extra_packets=[p for p in pkts if p != 0] if 0 in self._selected_packets() else pkts)
            elif nid == 129:
                data = gen.msg_129_validated_train_data({
                    "nc_cdtrain": 0, "nc_train": 0, "l_train_m": self._p("l_train"),
                    "v_maxtrain_kmh": self._p("v_maxtrain"), "m_loadinggauge": 1,
                    "m_axleloadcat": 2, "m_airtight": 0, "n_axle": int(self._p("n_axle"))},
                    extra_packets=[p for p in pkts if p != 11])
            elif nid == 32:
                data = gen.msg_32_system_version(m_version=self.version.get(), m_ack=int(self._p("m_ack")))
            elif nid in (155, 156, 159, 154, 146, 132):
                data = getattr(gen, {
                    155: "msg_155_initiate_session", 156: "msg_156_terminate_session",
                    159: "msg_159_session_established", 154: "msg_154_no_compatible_version",
                    146: "msg_146_acknowledgement", 132: "msg_132_ma_request"}[nid])()
            elif nid == 16:
                data = gen.msg_16_unconditional_emergency_stop(m_ack=int(self._p("m_ack")))
            elif nid == 38:
                data = gen.msg_38_ack_session_establishment(m_ack=int(self._p("m_ack")))
            elif nid == 41:
                data = gen.msg_41_train_accepted(self.t_train.get(), m_ack=int(self._p("m_ack")))
            elif nid == 40:
                data = gen.msg_40_train_rejected(self.t_train.get(), m_ack=int(self._p("m_ack")))
            else:
                from .messages import build_message
                nid_engine = 0x0012AB if direction == "bord" else None
                nid_lrbg = (self.nid_c.get() << 14) | self.nid_bg.get()
                data = build_message(nid, "train_to_track" if direction == "bord" else "track_to_train",
                                     self.t_train.get(), m_ack=int(self._p("m_ack")),
                                     nid_lrbg=nid_lrbg, nid_engine=nid_engine, packets=pkts)
        except Exception as exc:
            messagebox.showerror("Erreur", str(exc))
            return
        self.last_data = data
        self.last_kind = "message"
        self.out.delete("1.0", "end")
        self.out.insert("end", export_text(data, "message"))

    def _validate(self):
        nid = getattr(self, "current_nid", None)
        if nid is None:
            return
        direction = "track_to_train" if self.direction.get() == "sol" else "train_to_track"
        errors = validate_message(nid, direction, self._selected_packets())
        if errors:
            messagebox.showerror("Non conforme (ch.8)", "\n".join(errors))
        else:
            messagebox.showinfo("Conforme", f"Message {nid} conforme aux règles du chapitre 8.")

    def _save(self, fmt):
        if not hasattr(self, "last_data"):
            messagebox.showwarning("Sauvegarde", "Générez d'abord un message.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json" if fmt == "json" else ".txt",
            filetypes=[("JSON", "*.json"), ("Texte", "*.txt")])
        if not path:
            return
        content = export_json(self.last_data, self.last_kind) if fmt == "json" else export_text(self.last_data, self.last_kind)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        messagebox.showinfo("Enregistré", path)

    def _open_decode(self):
        path = filedialog.askopenfilename(filetypes=[("JSON/TXT", "*.json *.txt"), ("Tous", "*.*")])
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            content = f.read()
        try:
            obj = json.loads(content)
            hexstr = obj.get("hex", "")
            kind = "telegram" if "Eurobalise" in obj.get("format", "") else ("loop" if "Euroloop" in obj.get("format", "") else "message")
            data = bytes.fromhex(hexstr)
        except Exception:
            messagebox.showerror("Lecture", "Impossible de lire le fichier (hex attendu).")
            return
        self.out.delete("1.0", "end")
        self.out.insert("end", export_text(data, kind))


def main():
    app = EtcsGui()
    app.mainloop()


if __name__ == "__main__":
    main()
