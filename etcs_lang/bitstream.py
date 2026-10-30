"""MSB-first bit stream reader/writer, the basis of the ERTMS/ETCS language."""


class BitWriter:
    """Accumulates bits, most significant bit first, as per SUBSET-026 ch.7."""

    def __init__(self):
        self._bits = []

    def write_uint(self, value: int, length: int) -> None:
        if value < 0 or value >= (1 << length):
            raise ValueError(f"value {value} does not fit in {length} bits")
        for i in range(length - 1, -1, -1):
            self._bits.append((value >> i) & 1)

    def write_bits(self, bits) -> None:
        for b in bits:
            self._bits.append(1 if b else 0)

    def write_bytes(self, data: bytes) -> None:
        for byte in data:
            self.write_uint(byte, 8)

    def __len__(self) -> int:
        return len(self._bits)

    def to_bits(self) -> list:
        return list(self._bits)

    def to_bytes(self, pad: bool = True) -> bytes:
        """Pack bits into bytes. With pad=False, a trailing partial byte is
        kept as a bit string so callers can embed it bit-exactly (e.g. the
        14-bit packet 0 of a balise telegram, ch.8 §8.4.2.3)."""
        bits = self._bits[:]
        if pad:
            while len(bits) % 8:
                bits.append(0)
        out = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            chunk = bits[i : i + 8]
            for b in chunk:
                byte = (byte << 1) | b
            byte <<= (8 - len(chunk))  # left-align partial trailing byte
            out.append(byte)
        return bytes(out)

    def to_bin(self) -> str:
        return "".join(str(b) for b in self._bits)


class BitReader:
    """Reads bits MSB-first from a bit list or bytes."""

    def __init__(self, data):
        if isinstance(data, (bytes, bytearray)):
            bits = []
            for byte in data:
                for i in range(7, -1, -1):
                    bits.append((byte >> i) & 1)
            self._bits = bits
        else:
            self._bits = [1 if b else 0 for b in data]
        self._pos = 0

    def read_uint(self, length: int) -> int:
        if self._pos + length > len(self._bits):
            raise EOFError("not enough bits remaining")
        value = 0
        for _ in range(length):
            value = (value << 1) | self._bits[self._pos]
            self._pos += 1
        return value

    def remaining(self) -> int:
        return len(self._bits) - self._pos

    def peek_uint(self, length: int) -> int:
        saved = self._pos
        try:
            return self.read_uint(length)
        finally:
            self._pos = saved

    @property
    def pos(self) -> int:
        return self._pos

    def to_bits(self):
        return self._bits[self._pos :]

    def read_bits(self, n: int):
        """Read n raw bits as a list (bit-exact, may span byte boundaries)."""
        return [self.read_uint(1) for _ in range(n)]
