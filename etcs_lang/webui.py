"""Web-based graphical interface to build ERTMS/ETCS messages, step by step.

Run with:  python -m etcs_lang.webui

Flow:
  Step 1: choose kind = Eurobalise telegram OR Euroradio message (no Euroloop).
  Step 2 (telegram): configure the 50-bit balise header (ch.8 §8.4.2.1),
     pick packets, set N_TOTAL -> one telegram per balise is generated.
  Step 2 (radio): pick a message from the bord->sol / sol->bord lists
     (ch.8 §8.5.2/§8.5.3), pick allowed packets (§8.4.4.4), generate.

Generated results can be downloaded in readable formats (JSON decoded + hex,
or plain text).
"""

import json

from .generator import MessageGenerator
from .messages import TRAIN_TO_TRACK_MESSAGES, TRACK_TO_TRAIN_MESSAGES, build_message
from .packets import (
    packet_name, build_packet_0_vbcmk, build_packet_2_system_version_order,
    build_packet_3_national_values, build_packet_15_l2_ma, build_packet_21_gradient,
    build_packet_27_issp, build_packet_41_level_transition,
    build_packet_42_session_mgmt, build_packet_44_external_data,
    build_packet_65_tsr, build_packet_136_infill_location,
)
from .telegram import build_telegram, BALISE_HEADER_BITS
from .rules import allowed_packets, validate_message
from .exporter import export_json, export_text

try:
    import webview
except ImportError:  # GUI optional dependency
    webview = None


# Packets that can be built and put in a balise telegram (track-to-train)
BALISE_PACKET_BUILDERS = {
    0: lambda g, p: build_packet_0_vbcmk(int(p.get("nid_vbcmk", 0))),
    2: lambda g, p: build_packet_2_system_version_order(p.get("version", g.system_version)),
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
    44: lambda g, p: build_packet_44_external_data(1, b"\x01\x02\x03"),
    65: lambda g, p: build_packet_65_tsr(int(p.get("q_scale", 0)), int(p.get("nid_tsr", 1)),
                                         500, 200, 1, 60),
    136: lambda g, p: build_packet_136_infill_location(0, g.nid_c, g.nid_bg),
}


class Api:
    """Backend exposed to the webview JS."""

    # ---- radio messages ----
    def messages(self, direction):
        table = TRACK_TO_TRAIN_MESSAGES if direction == "sol" else TRAIN_TO_TRACK_MESSAGES
        return [{"id": nid, "title": t} for nid, t in sorted(table.items())]

    def packets(self, nid, direction):
        d = "track_to_train" if direction == "sol" else "train_to_track"
        mandatory, optional = allowed_packets(nid, d)
        def label(p):
            return {"num": p, "name": packet_name(p, d)}
        return {"mandatory": [label(p) for p in mandatory],
                "optional": [label(p) for p in optional]}

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
                data = build_message(nid, "train_to_track", gen.t_train,
                                     nid_engine=gen.nid_engine)
        return {
            "hex": data.hex(),
            "json": export_json(data, "message"),
            "text": export_text(data, "message"),
        }

    # ---- balise telegrams ----
    def balise_packets(self):
        """Packets available in a balise telegram, with names (ch.7 §7.4.2)."""
        return [{"num": n, "name": packet_name(n, "track_to_train")}
                for n in sorted(BALISE_PACKET_BUILDERS)]

    def generate_telegram(self, payload):
        """Generate one telegram per balise of the group (N_TOTAL, ch.8 §8.4.2.1).

        Packet 0 (VBC marker) is placed first if selected (§8.4.2.3), packet 255
        is appended automatically at the end of every telegram.
        """
        p = json.loads(payload) if isinstance(payload, str) else payload
        version = p.get("version", "3.0")
        nid_c = int(p.get("nid_c", 1))
        nid_bg = int(p.get("nid_bg", 100))
        n_total = max(1, min(8, int(p.get("n_total", 1))))   # N_TOTAL: 3 bits
        m_mcount = int(p.get("m_mcount", 0))
        m_dup = int(p.get("m_dup", 0))
        q_link = int(p.get("q_link", 0))
        q_updown = int(p.get("q_updown", 1))
        gen = MessageGenerator("sol", system_version=version, nid_c=nid_c, nid_bg=nid_bg)
        selected = [int(x) for x in p.get("packets", [])]
        pkts = []
        if 0 in selected:
            pkts.append(BALISE_PACKET_BUILDERS[0](gen, p))  # packet 0 first (§8.4.2.3)
        for n in selected:
            if n != 0 and n in BALISE_PACKET_BUILDERS:
                pkts.append(BALISE_PACKET_BUILDERS[n](gen, p))
        telegrams = []
        for n_pig in range(n_total):
            data = build_telegram(version, n_pig=n_pig, n_total=n_total, m_dup=m_dup,
                                  m_mcount=m_mcount, nid_c=nid_c, nid_bg=nid_bg,
                                  q_link=q_link, q_updown=q_updown, packets=pkts)
            telegrams.append({
                "n_pig": n_pig,
                "hex": data.hex(),
                "json": export_json(data, "telegram"),
                "text": export_text(data, "telegram"),
            })
        return {"n_total": n_total, "telegrams": telegrams}


HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>ERTMS/ETCS B4R1 - Générateur de messages</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:16px;background:#f5f6f8}
 h1{font-size:18px} h2{font-size:15px;margin:8px 0}
 .steps{display:flex;gap:8px;margin-bottom:10px}
 .step{padding:6px 12px;border-radius:4px;background:#dde;color:#224;font-weight:bold}
 .step.active{background:#246;color:#fff}
 .row{display:flex;gap:16px;flex-wrap:wrap}
 .col{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px}
 select,input{width:100%;margin:2px 0;box-sizing:border-box}
 .pkt{display:block} button{margin:4px 4px 4px 0;padding:6px 10px;cursor:pointer}
 pre{background:#111;color:#0f0;padding:8px;max-height:280px;overflow:auto;font-size:12px}
 #err{color:#a00;font-weight:bold;white-space:pre-wrap}
 label{font-size:12px;color:#444;display:block;margin-top:4px}
 .kindbtn{font-size:15px;padding:14px 18px}
 .hidden{display:none}
</style></head><body>
<h1>ERTMS/ETCS B4R1 — Création de messages (SUBSET-026 ch.6/7/8)</h1>

<div class="steps">
 <div class="step active" id="s1">1. Type</div>
 <div class="step" id="s2">2. Configuration</div>
 <div class="step" id="s3">3. Résultat</div>
</div>

<div id="err"></div>

<!-- STEP 1 -->
<div id="step1">
  <h2>Étape 1 — Que voulez-vous créer ?</h2>
  <button class="kindbtn" onclick="chooseKind('telegram')">📡 Télégramme Eurobalise</button>
  <button class="kindbtn" onclick="chooseKind('radio')">📻 Message radio (Euroradio)</button>
</div>

<!-- STEP 2 : TELEGRAM -->
<div id="step2tg" class="hidden">
  <h2>Étape 2 — Télégramme balise : en-tête (50 bits, ch.8 §8.4.2.1) + paquets</h2>
  <div class="row">
   <div class="col" style="width:260px">
    <label>Q_UPDOWN (1=up-link sol→bord)</label><select id="tg_q_updown"><option value="1">1 - up-link</option><option value="0">0 - down-link</option></select>
    <label>M_VERSION (version système, ch.6)</label>
    <select id="tg_version"><option>1.0</option><option>1.1</option><option>2.0</option><option>2.1</option><option>2.2</option><option>2.3</option><option selected>3.0</option></select>
    <label>N_TOTAL (nombre de balises du groupe, 3 bits)</label><input id="tg_n_total" type="number" value="1" min="1" max="8">
    <label>M_MCOUNT (compteur, 8 bits)</label><input id="tg_m_mcount" type="number" value="0" min="0" max="255">
    <label>M_DUP (0=no dup, 1=dup of previous, 2=dup of next)</label><select id="tg_m_dup"><option value="0">0</option><option value="1">1</option><option value="2">2</option></select>
    <label>NID_C (pays/région, 10 bits)</label><input id="tg_nid_c" type="number" value="1" min="0" max="1023">
    <label>NID_BG (identité groupe, 14 bits)</label><input id="tg_nid_bg" type="number" value="100" min="0" max="16382">
    <label>Q_LINK (1=linked)</label><select id="tg_q_link"><option value="0">0 - unlinked</option><option value="1">1 - linked</option></select>
   </div>
   <div class="col" style="width:300px">
    <b>Paquets du télégramme (ch.7 §7.4.2) :</b><div id="tg_packets"></div>
    <hr><b>Paramètres des paquets</b>
    <label>Q_SCALE (0/1/2)</label><input id="q_scale" value="0">
    <label>V_EMA km/h</label><input id="v_ema" value="80">
    <label>T_EMA s</label><input id="t_ema" value="0">
    <label>L_ENDSECTION m</label><input id="l_endsection" value="5000">
    <label>D_DP m</label><input id="d_dp" value="100">
    <label>V_RELEASEDP km/h</label><input id="v_releasedp" value="0">
    <label>NID_VBCMK (paquet 0)</label><input id="nid_vbcmk" value="0">
    <label>NID_TSR (paquet 65)</label><input id="nid_tsr" value="1">
   </div>
  </div>
  <button onclick="genTelegram()">Générer le(s) télégramme(s)</button>
  <button onclick="back()">← Retour étape 1</button>
</div>

<!-- STEP 2 : RADIO -->
<div id="step2radio" class="hidden">
  <h2>Étape 2 — Message radio : direction, message, paquets autorisés</h2>
  <div class="row">
   <div class="col" style="width:280px">
    <label>Direction</label>
    <select id="dir" onchange="loadMessages()">
     <option value="sol">Sol → Bord (track-to-train, ch.8 §8.7)</option>
     <option value="bord">Bord → Sol (train-to-track, ch.8 §8.6)</option>
    </select>
    <label>Version système (ch.6)</label>
    <select id="version"><option>1.0</option><option>1.1</option><option>2.0</option><option>2.1</option><option>2.2</option><option>2.3</option><option selected>3.0</option></select>
    <label>NID_C</label><input id="nid_c" type="number" value="1">
    <label>NID_BG (LRBG)</label><input id="nid_bg" type="number" value="100">
    <label>T_TRAIN (ticks 10 ms)</label><input id="t_train" type="number" value="0">
    <label>Message</label>
    <select id="msg" size="10" style="height:220px" onchange="loadPackets()"></select>
   </div>
   <div class="col" style="width:320px">
    <b>Paquets autorisés (ch.8 §8.4.4.4)</b>
    <div id="mandatory"></div><div id="packets"></div>
    <hr><b>Paramètres</b>
    <label>M_ACK (0/1)</label><input id="m_ack" value="0">
    <label>V_EMA km/h</label><input id="v_ema2" value="80">
    <label>T_EMA s</label><input id="t_ema2" value="0">
    <label>L_ENDSECTION m</label><input id="l_endsection2" value="5000">
    <label>D_DP m</label><input id="d_dp2" value="100">
    <label>V_RELEASEDP km/h</label><input id="v_releasedp2" value="0">
    <label>D_SR m</label><input id="d_sr" value="2000">
    <label>Q_SCALE (0/1/2)</label><input id="q_scale2" value="0">
    <label>D_LRBG m</label><input id="d_lrbg" value="1200">
    <label>V_TRAIN km/h</label><input id="v_train" value="60">
    <label>M_MODE</label><input id="m_mode" value="0">
    <label>M_LEVEL</label><input id="m_level" value="2">
    <label>L_TRAIN m</label><input id="l_train" value="200">
    <label>V_MAXTRAIN km/h</label><input id="v_maxtrain" value="160">
    <label>N_AXLE</label><input id="n_axle" value="20">
   </div>
  </div>
  <button onclick="validate()">Valider conformité ch.8</button>
  <button onclick="generate()">Générer le message</button>
  <button onclick="back()">← Retour étape 1</button>
</div>

<!-- STEP 3 -->
<div id="step3" class="hidden">
  <h2>Étape 3 — Résultat</h2>
  <button onclick="save('json')">Télécharger JSON</button>
  <button onclick="save('txt')">Télécharger TXT</button>
  <button onclick="back()">← Retour étape 1</button>
  <pre id="out"></pre>
</div>

<script>
window.onerror=function(m,s,l){const e=document.getElementById('err');if(e)e.textContent='Erreur JS: '+m+' (ligne '+l+')';};
function getApi(){return window.pywebview?window.pywebview.api:null;}
function go(n){ ['step1','step2tg','step2radio','step3'].forEach(id=>document.getElementById(id).classList.add('hidden'));
  document.getElementById('s1').classList.toggle('active',n===1);
  document.getElementById('s2').classList.toggle('active',n===2);
  document.getElementById('s3').classList.toggle('active',n===3); }
function back(){ go(1); document.getElementById('err').textContent=''; }
async function chooseKind(kind){
  document.getElementById('err').textContent='';
  if(kind==='telegram'){ go(2); document.getElementById('step2tg').classList.remove('hidden'); await loadBalisePackets(); }
  else { go(2); document.getElementById('step2radio').classList.remove('hidden'); await loadMessages(); }
}
async function loadBalisePackets(){
  const api=getApi(); if(!api)return;
  const list=await api.balise_packets();
  const box=document.getElementById('tg_packets'); box.innerHTML='';
  list.forEach(p=>{ const l=document.createElement('label'); l.className='pkt';
    const c=document.createElement('input'); c.type='checkbox'; c.value=p.num;
    l.append(c,' paquet '+p.num+' — '+p.name); box.append(l); });
}
async function loadMessages(){
  const api=getApi(); if(!api)return;
  const dir=document.getElementById('dir').value;
  const list=await api.messages(dir);
  const sel=document.getElementById('msg'); sel.innerHTML='';
  list.forEach(m=>{const o=document.createElement('option');o.value=m.id;o.text=m.id+' - '+m.title;sel.add(o);});
  loadPackets();
}
async function loadPackets(){
  const api=getApi(); if(!api)return;
  const nid=document.getElementById('msg').value;
  const dir=document.getElementById('dir').value;
  if(!nid)return;
  let r;
  try{ r=await api.packets(parseInt(nid),dir); }
  catch(e){ document.getElementById('err').textContent='Erreur paquets: '+e; return; }
  const mandNums=r.mandatory.map(p=>p.num);
  document.getElementById('mandatory').innerHTML='<i>Obligatoires: '+(r.mandatory.map(p=>p.num+' '+p.name).join(', ')||'aucun')+'</i>';
  const box=document.getElementById('packets'); box.innerHTML='';
  if(!r.optional.length && !r.mandatory.length){ box.innerHTML='<i>Ce message ne contient aucun paquet (ch.8 §8.6/§8.7).</i>'; return; }
  const seen=new Set();
  [...r.mandatory,...r.optional].forEach(p=>{
    if(seen.has(p.num))return; seen.add(p.num);
    const l=document.createElement('label'); l.className='pkt';
    const c=document.createElement('input'); c.type='checkbox'; c.value=p.num;
    if(mandNums.includes(p.num)){c.checked=true;c.disabled=true;}
    l.append(c,' paquet '+p.num+' — '+p.name); box.append(l);
  });
}
function g(id){return document.getElementById(id).value;}
function tgPayload(){
  const ps=[...document.querySelectorAll('#tg_packets input:checked')].map(c=>c.value);
  return {version:g('tg_version'),nid_c:g('tg_nid_c'),nid_bg:g('tg_nid_bg'),n_total:g('tg_n_total'),
    m_mcount:g('tg_m_mcount'),m_dup:g('tg_m_dup'),q_link:g('tg_q_link'),q_updown:g('tg_q_updown'),
    packets:ps,q_scale:g('q_scale'),v_ema:g('v_ema'),t_ema:g('t_ema'),l_endsection:g('l_endsection'),
    d_dp:g('d_dp'),v_releasedp:g('v_releasedp'),nid_vbcmk:g('nid_vbcmk'),nid_tsr:g('nid_tsr')};
}
function payload(){
  const ps=[...document.querySelectorAll('#packets input:checked')].map(c=>c.value);
  return {direction:g('dir'),nid:g('msg'),version:g('version'),nid_c:g('nid_c'),nid_bg:g('nid_bg'),
    t_train:g('t_train'),packets:ps,m_ack:g('m_ack'),v_ema:g('v_ema2'),t_ema:g('t_ema2'),
    l_endsection:g('l_endsection2'),d_dp:g('d_dp2'),v_releasedp:g('v_releasedp2'),d_sr:g('d_sr'),
    q_scale:g('q_scale2'),d_lrbg:g('d_lrbg'),v_train:g('v_train'),m_mode:g('m_mode'),
    m_level:g('m_level'),l_train:g('l_train'),v_maxtrain:g('v_maxtrain'),n_axle:g('n_axle')};
}
async function validate(){
  const api=getApi(); if(!api)return;
  const p=payload(); const errs=await api.validate(parseInt(p.nid),p.direction,p.packets);
  document.getElementById('err').textContent=errs.length?('NON CONFORME: '+errs.join(' | ')):'Conforme ch.8 ✔';
}
let last=null;
async function genTelegram(){
  const api=getApi(); if(!api)return;
  document.getElementById('err').textContent='';
  try{
    const r=await api.generate_telegram(JSON.stringify(tgPayload()));
    last={kind:'telegram',items:r.telegrams};
    document.getElementById('out').textContent=
      'Groupe de '+r.n_total+' balise(s) — un télégramme par balise (N_PIG 0..'+(r.n_total-1)+') :\n\n'+
      r.telegrams.map(t=>'--- Balise N_PIG='+t.n_pig+' ---\n'+t.text).join('\n\n');
    go(3); document.getElementById('step3').classList.remove('hidden');
  }catch(e){ document.getElementById('err').textContent='Erreur: '+e; }
}
async function generate(){
  const api=getApi(); if(!api)return;
  document.getElementById('err').textContent='';
  try{ last={kind:'message',items:[await api.generate(JSON.stringify(payload()))]};
    document.getElementById('out').textContent=last.items[0].text;
    go(3); document.getElementById('step3').classList.remove('hidden');
  }catch(e){ document.getElementById('err').textContent='Erreur: '+e; }
}
function save(fmt){
  if(!last)return;
  let content;
  if(last.kind==='telegram'){
    content = fmt==='json' ? JSON.stringify({format:'Eurobalise group',telegrams:last.items.map(t=>JSON.parse(t.json))},null,2)
                           : last.items.map(t=>t.text).join('\n\n');
  } else {
    content = fmt==='json' ? last.items[0].json : last.items[0].text;
  }
  const blob=new Blob([content],{type:'text/plain'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='etcs_'+(last.kind==='telegram'?'telegrammes':'message')+'.'+fmt; a.click();
}
if(window.pywebview){ /* ready */ }
else { window.addEventListener('pywebviewready', function(){}); }
</script></body></html>"""


def main():
    if webview is None:
        raise SystemExit("pip install pywebview is required for the GUI (pip install pywebview)")
    api = Api()
    webview.create_window(
        "ERTMS/ETCS B4R1 - Générateur de messages (étapes)",
        html=HTML, width=1250, height=800)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
