"""Message/packet composition rules per SUBSET-026-8 §8.4.4.4, §8.5, §8.6, §8.7.

Defines, for each radio message, which packets are mandatory and which are
allowed as optional packets, so that the GUI only proposes compliant
combinations.
"""

# ch.8 §8.4.4.4.1.1: common optional packets (track-to-train)
COMMON_OPTIONAL_PACKETS = [3, 5, 31, 32, 39, 40, 41, 42, 44, 45, 51, 52, 57, 58,
                            64, 65, 66, 67, 68, 69, 70, 71, 73, 74, 79, 88, 131,
                            138, 139, 140, 180]

# ch.8 §8.4.4.4.1: track-to-train messages possibly including optional packets
TRACK_TO_TRAIN_OPTIONAL = {
    2:  {"mandatory": [], "optional": [63]},
    3:  {"mandatory": [15], "optional": [21, 27, 49, 80] + COMMON_OPTIONAL_PACKETS},
    4:  {"mandatory": [15], "optional": [3, 5, 31, 39, 40, 44, 45, 51, 58, 64, 65, 66,
                                          67, 68, 69, 71, 73, 74, 79, 88, 131, 140]},
    9:  {"mandatory": [], "optional": [49, 80]},
    24: {"mandatory": [], "optional": [21, 27] + COMMON_OPTIONAL_PACKETS},  # from RBC
    28: {"mandatory": [], "optional": [3, 44, 49]},
    33: {"mandatory": [15], "optional": [21, 27, 49, 80] + COMMON_OPTIONAL_PACKETS},
    37: {"mandatory": [15], "optional": [5, 21, 27, 39, 40, 41, 44, 49, 51, 52, 65, 68,
                                          69, 70, 71, 80, 88, 138, 139]},
}

# ch.8 §8.4.4.4.2 - §8.4.4.4.5: train-to-track optional packets
TRAIN_TO_TRACK_OPTIONAL = {
    136: {"mandatory": [0], "optional": [4, 5, 44]},       # 8.4.4.4.2: packet 0 or 1
    157: {"mandatory": [0], "optional": [4, 5, 10, 11, 44]},  # 8.4.4.4.3
    132: {"mandatory": [], "optional": [9]},                # 8.4.4.4.4
    131: {"mandatory": [], "optional": [12]},               # 8.4.4.4.5
}

# Messages with no packets at all (ch.8 §8.6/§8.7 field tables)
NO_PACKET_MESSAGES = {
    "track_to_train": [5, 6, 7, 8, 15, 16, 18, 27, 32, 34, 38, 39, 40, 41, 43, 45],
    "train_to_track": [130, 133, 137, 138, 146, 147, 149, 150, 153, 154, 155, 156, 158, 159],
}

# Messages whose mandatory content is a packet (besides optional ones)
MANDATORY_PACKETS = {
    2: [], 3: [15], 4: [15], 129: [11], 136: [0], 157: [0], 33: [15], 37: [15],
}


def allowed_packets(nid_message, direction):
    """Return (mandatory, optional) packet lists allowed in this message (ch.8)."""
    if direction == "track_to_train":
        if nid_message in TRACK_TO_TRAIN_OPTIONAL:
            spec = TRACK_TO_TRAIN_OPTIONAL[nid_message]
            return list(spec["mandatory"]), list(spec["optional"])
        if nid_message in NO_PACKET_MESSAGES["track_to_train"]:
            return [], []
        return [], []
    else:
        if nid_message in TRAIN_TO_TRACK_OPTIONAL:
            spec = TRAIN_TO_TRACK_OPTIONAL[nid_message]
            mand = [p if p != 0 else 0 for p in spec["mandatory"]]
            return mand, list(spec["optional"])
        if nid_message in (129,):
            return [11], []
        if nid_message in NO_PACKET_MESSAGES["train_to_track"]:
            return [], []
        return [], []


def validate_message(nid_message, direction, packet_numbers):
    """Check a packet combination against ch.8 rules.

    Returns a list of error strings (empty if compliant).
    """
    errors = []
    mandatory, optional = allowed_packets(nid_message, direction)
    allowed = set(mandatory) | set(optional)
    for p in mandatory:
        if p not in packet_numbers:
            errors.append(f"packet {p} is mandatory for message {nid_message}")
    for p in packet_numbers:
        if p not in allowed:
            errors.append(f"packet {p} is not allowed in message {nid_message} ({direction})")
    # ch.8 §8.4.1.4/§8.4.1.5: at most one instance of the same packet type
    # (except 44, 65, 66, 88, 136, 145, 254, 0 in balise messages)
    multi_allowed = {44, 65, 66, 88, 136, 145, 254}
    seen = set()
    for p in packet_numbers:
        if p in seen and p not in multi_allowed:
            errors.append(f"packet {p} appears more than once (forbidden by ch.8 §8.4.1)")
        seen.add(p)
    return errors
