# ERTMS/ETCS B4R1 language toolkit (SUBSET-026 chapters 6, 7, 8)

Outil Python capable de **créer et décoder des messages ETCS bord (train→track) et sol (track→train)** conformes au langage ERTMS/ETCS défini par le SUBSET-026 version 4.0.0 (Baseline 4 R1) :

- **chapitre 6** — gestion des versions système (`M_VERSION`, enveloppes X=1/2/3, versions supportées bord) ;
- **chapitre 7** — langage ERTMS/ETCS : variables (§7.5, 226 extraites automatiquement), paquets track→train (§7.4.2) et train→track (§7.4.3) ;
- **chapitre 8** — messages : en-têtes de télégrammes Eurobalise (50 bits, §8.4.2), messages Euroloop (33 bits, §8.4.3), messages Euroradio (§8.4.4.6) avec `L_MESSAGE` en octets, messages bord §8.6 (129, 132, 136, 146, 154, 155, 156, 159…) et sol §8.7 (2, 3, 16, 32, 38, 41…).

## Installation

Aucune dépendance externe (Python ≥ 3.10 standard library uniquement).

```bash
pip install -e .   # optionnel ; sinon utiliser directement le package etcs_lang/
```

## Utilisation (API)

```python
from etcs_lang import MessageGenerator

sol = MessageGenerator("sol", system_version="3.0", nid_c=1, nid_bg=100)
bord = MessageGenerator("bord", system_version="3.0", nid_engine=0x0012AB)

# sol -> bord : Movement Authority (message 3 + paquet 15)
ma = sol.msg_3_movement_authority({
    "q_scale": 1, "v_ema_kmh": 100, "t_ema_s": 0, "l_endsection_m": 8000,
    "sections_m": [], "q_dangerpoint": 1, "d_dp_m": 100,
    "v_releasedp_kmh": 0, "q_overlap": 0}, m_ack=1)
print(ma.hex())

# bord -> sol : Train Position Report (message 136 + paquet 0)
pos = bord.msg_136_position_report(d_lrbg_m=1500, v_train_kmh=80, m_level=2)

# bord -> sol : session (155), version (154), acquittement (146)
sess = bord.msg_155_initiate_session()

# sol -> bord : télégramme Eurobalise (paquets 2 + 3 + 255)
tg = sol.balise_telegram(packets=[sol.packet_system_version_order(),
                                  sol.packet_national_values()])

# décodage
msg = MessageGenerator.decode(ma)          # RadioMessage
tg_dec = MessageGenerator.decode_balise(tg)  # BaliseTelegram
```

## Utilisation (CLI)

```bash
python -m etcs_lang.cli list-messages                          # liste messages + versions
python -m etcs_lang.cli gen sol msg3 --v-ema 100 --l-endsection 8000 --q-scale 1
python -m etcs_lang.cli gen bord msg136 --d-lrbg 1500 --v-train 80
python -m etcs_lang.cli gen bord msg155
python -m etcs_lang.cli gen sol msg32 --version 3.0
python -m etcs_lang.cli gen sol telegram --packets 2,3         # télégramme balise
python -m etcs_lang.cli decode <hex>                           # décoder un message radio
python -m etcs_lang.cli decode <hex> --kind telegram           # décoder un télégramme
python -m etcs_lang.cli decode <hex> --kind loop               # décoder un message Euroloop
```

## Structure du paquet

| Fichier | Rôle |
|---|---|
| `etcs_lang/bitstream.py` | lecture/écriture de bits MSB-first |
| `etcs_lang/versions.py` | versions système (ch.6) : `M_VERSION` 7 bits, enveloppes |
| `etcs_lang/variables.py` | variables (ch.7 §7.5) + conversions d'unités (Q_SCALE, vitesses 5 km/h, BCD, texte ISO 8859-1) |
| `etcs_lang/packets.py` | paquets ch.7 §7.4 : construction bit-exacte (`L_PACKET` = paquet complet en bits) et décodage |
| `etcs_lang/messages.py` | messages Euroradio ch.8 §8.6/§8.7, `L_MESSAGE` en octets |
| `etcs_lang/telegram.py` | télégrammes Eurobalise (50 bits) et messages Euroloop (33 bits), ch.8 §8.4.2/§8.4.3 |
| `etcs_lang/generator.py` | fabrique haut niveau `MessageGenerator("sol"/"bord")` |
| `etcs_lang/cli.py` | interface en ligne de commande |
| `etcs_lang/data/*.json` | base extraite automatiquement des PDF SUBSET-026 (226 variables, 66 paquets, 43 messages) |
| `tools/extract_spec.py`, `tools/extract_packets.py` | extracteurs des spécifications |
| `tests/test_etcs_lang.py` | tests unitaires (round-trip encode/décode) |

## Tests

```bash
python -m unittest discover -s tests -v
```

## Notes de conformité

- `L_MESSAGE` (10 bits) = longueur du message **en octets**, en-tête inclus (SUBSET-026-7 §7.5.1.48 ; ch.8 §8.4.4.2), complété par du padding à zéro pour obtenir un nombre entier d'octets (ch.8 §8.4.4.5).
- `L_PACKET` (13 bits) = longueur du paquet **en bits, en-tête inclus** (SUBSET-026-7 §7.5.1.49).
- Les paquets dans un télégramme/message sont concaténés au bit près (ch.8 §8.4.2.2 : un paquet ne peut pas être scindé entre deux balises).
- `M_VERSION` (7 bits) : 3 MSB = X (version incompatible), 4 LSB = Y (compatible) — ch.7 §7.5.1.79 et ch.6 §6.4.
- Le paquet 255 (fin d'information) est un `NID_PACKET` = 255 sur 8 bits.
