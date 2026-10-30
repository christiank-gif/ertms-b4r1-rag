"""Web-based graphical interface to build ERTMS/ETCS bord/sol messages.

Run with:  python -m etcs_lang.webui   (then open the printed URL)

The UI only proposes messages and packets allowed by SUBSET-026-8
(ch.8 §8.4.4.4, §8.6, §8.7). Generated messages can be saved in readable
formats (JSON decoded + hex, or plain text).
"""

import json
import threading
import webbrowser

from .generator import MessageGenerator
from .messages import TRAIN_TO_TRACK_MESSAGES, TRACK_TO_TRAIN_MESSAGES
from .rules import allowed_packets, validate_message
from .exporter import export_json, export_text

try:
    import webview
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pip install pywebview is required for the GUI") from exc


class Api:
    """Backend exposed to the webview JS."""

    def messages(self, direction):
        table = TRACK_TO_TRAIN_MESSAGES if direction == "sol" else TRAIN_TO_TRACK_MESSAGES
        return [{"id": nid, "title": t} for nid, t in sorted(table.items())]

    def packets(self, nid, direction):
        d = "track_to_train" if direction == "sol" else "train_to_track"
        mandatory, optional = allowed_packets(nid, d)
        return {"mandatory": mandatory, "optional": optional}

    def validate(self, nid, direction, packets):
        d = "track_to_train" if direction == "sol" else "train_to_track"
        return validate_message(nid, d, packets)

    def generate(self, payload):
        p = json.loads(payload) if isinstance(payload, str) else payload
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
                from .packets import build_packet_136_infill_location
                extra.append(build_packet_136_infill_location(0, gen.nid_c, gen.nid_bg))
            if nid == 3:
                ma = {"q_scale": int(q("q_scale")), "v_ema_kmh": q("v_ema"),
                      "t_ema_s": q("t_ema"), "l_endsection_m": q("l_endsection"),
                      "sections_m": [], "q_dangerpoint": 1, "d_dp_m": q("d_dp"),
                      "v_releasedp_kmh": q("v_releasedp"), "q_overlap": 0}
                data = gen.msg_3_movement_authority(ma, m_ack=int(q("m_ack")),
                                                    extra_packets=[e for e in extra if True])
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
                from .messages import build_message
                data = build_message(nid, "track_to_train", gen.t_train,
                                     m_ack=int(q("m_ack")), nid_lrbg=gen.nid_lrbg,
                                     packets=extra)
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
                from .messages import build_message
                data = build_message(nid, "train_to_track", gen.t_train,
                                     nid_engine=gen.nid_engine)
        return {
            "hex": data.hex(),
            "json": export_json(data, "message"),
            "text": export_text(data, "message"),
        }


HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>ERTMS/ETCS B4R1 - Générateur de messages</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:16px;background:#f5f6f8}
 h1{font-size:18px} .row{display:flex;gap:16px}
 .col{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px}
 select,input{width:100%;margin:2px 0}
 .pkt{display:block} button{margin:4px 4px 4px 0;padding:6px 10px}
 pre{background:#111;color:#0f0;padding:8px;max-height:300px;overflow:auto;font-size:12px}
 #err{color:#a00;font-weight:bold}
 label{font-size:12px;color:#444}
</style></head><body>
<h1>ERTMS/ETCS B4R1 — Création de messages bord / sol (SUBSET-026 ch.6/7/8)</h1>
<div class="row">
 <div class="col" style="width:280px">
  <label>Direction</label>
  <select id="dir" onchange="loadMessages()">
   <option value="sol">Sol → Bord (track-to-train)</option>
   <option value="bord">Bord → Sol (train-to-track)</option>
  </select>
  <label>Version système (ch.6)</label>
  <select id="version"><option>1.0</option><option>1.1</option><option>2.0</option>
   <option>2.1</option><option>2.2</option><option>2.3</option><option selected>3.0</option></select>
  <label>NID_C</label><input id="nid_c" type="number" value="1">
  <label>NID_BG</label><input id="nid_bg" type="number" value="100">
  <label>T_TRAIN (ticks 10 ms)</label><input id="t_train" type="number" value="0">
  <label>Message</label>
  <select id="msg" size="10" style="height:220px" onchange="loadPackets()"></select>
 </div>
 <div class="col" style="width:300px">
  <b>Paquets autorisés (ch.8 §8.4.4.4)</b>
  <div id="mandatory"></div><div id="packets"></div>
  <hr>
  <b>Paramètres</b>
  <label>M_ACK (0/1)</label><input id="m_ack" value="0">
  <label>V_EMA km/h</label><input id="v_ema" value="80">
  <label>T_EMA s</label><input id="t_ema" value="0">
  <label>L_ENDSECTION m</label><input id="l_endsection" value="5000">
  <label>D_DP m</label><input id="d_dp" value="100">
  <label>V_RELEASEDP km/h</label><input id="v_releasedp" value="0">
  <label>D_SR m</label><input id="d_sr" value="2000">
  <label>Q_SCALE (0/1/2)</label><input id="q_scale" value="0">
  <label>D_LRBG m</label><input id="d_lrbg" value="1200">
  <label>V_TRAIN km/h</label><input id="v_train" value="60">
  <label>M_MODE</label><input id="m_mode" value="0">
  <label>M_LEVEL</label><input id="m_level" value="2">
  <label>L_TRAIN m</label><input id="l_train" value="200">
  <label>V_MAXTRAIN km/h</label><input id="v_maxtrain" value="160">
  <label>N_AXLE</label><input id="n_axle" value="20">
 </div>
 <div class="col" style="flex:1">
  <button onclick="validate()">Valider conformité ch.8</button>
  <button onclick="generate()">Générer le message</button>
  <button onclick="save('json')">Télécharger JSON</button>
  <button onclick="save('txt')">Télécharger TXT</button>
  <div id="err"></div>
  <pre id="out">Sélectionnez direction + message, cochez les paquets autorisés, puis « Générer ».</pre>
 </div>
</div>
<script>
const api = window.pywebview.api;
async function loadMessages(){
  const dir=document.getElementById('dir').value;
  const list=await api.messages(dir);
  const sel=document.getElementById('msg'); sel.innerHTML='';
  list.forEach(m=>{const o=document.createElement('option');o.value=m.id;o.text=m.id+' - '+m.title;sel.add(o);});
  loadPackets();
}
async function loadPackets(){
  const nid=document.getElementById('msg').value;
  const dir=document.getElementById('dir').value;
  const r=await api.packets(parseInt(nid),dir);
  document.getElementById('mandatory').innerHTML='<i>Obligatoires: '+r.mandatory.join(', ')+'</i>';
  const box=document.getElementById('packets'); box.innerHTML='';
  [...new Set([...r.mandatory,...r.optional])].forEach(p=>{
    const l=document.createElement('label'); l.className='pkt';
    const c=document.createElement('input'); c.type='checkbox'; c.value=p;
    if(r.mandatory.includes(p)){c.checked=true;c.disabled=true;}
    l.append(c,' paquet '+p); box.append(l);
  });
}
function payload(){
  const ps=[...document.querySelectorAll('#packets input:checked')].map(c=>c.value);
  const g=id=>document.getElementById(id).value;
  return {direction:g('dir'),nid:g('msg'),version:g('version'),nid_c:g('nid_c'),nid_bg:g('nid_bg'),
    t_train:g('t_train'),packets:ps,m_ack:g('m_ack'),v_ema:g('v_ema'),t_ema:g('t_ema'),
    l_endsection:g('l_endsection'),d_dp:g('d_dp'),v_releasedp:g('v_releasedp'),d_sr:g('d_sr'),
    q_scale:g('q_scale'),d_lrbg:g('d_lrbg'),v_train:g('v_train'),m_mode:g('m_mode'),
    m_level:g('m_level'),l_train:g('l_train'),v_maxtrain:g('v_maxtrain'),n_axle:g('n_axle')};
}
async function validate(){
  const p=payload(); const errs=await api.validate(parseInt(p.nid),p.direction,p.packets);
  document.getElementById('err').textContent=errs.length?('NON CONFORME: '+errs.join(' | ')):'Conforme ch.8 ✔';
}
let last=null;
async function generate(){
  document.getElementById('err').textContent='';
  try{ last=await api.generate(JSON.stringify(payload())); document.getElementById('out').textContent=last.text; }
  catch(e){ document.getElementById('err').textContent='Erreur: '+e; }
}
function save(fmt){
  if(!last) return;
  const blob=new Blob([fmt==='json'?last.json:last.text],{type:'text/plain'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='etcs_message.'+fmt; a.click();
}
loadMessages();
</script></body></html>"""


def main():
    api = Api()
    webview.create_window(
        "ERTMS/ETCS B4R1 - Générateur de messages bord/sol",
        html=HTML, width=1200, height=760)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
