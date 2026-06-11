import socket
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple


# =========================================================
# DATA STRUCTURES
# =========================================================

@dataclass
class CountRate:
    raw_counts: int
    cps: float
    total_count: int = 0


@dataclass
class TrigStatus:
    trig_active: bool
    trig_done: bool


# =========================================================
# CLIENT
# =========================================================

class PhotonScanner:
    """Client for the Red Pitaya photon counter server."""

    def __init__(self, host: str = '169.254.121.34', port: int = 5555, timeout: float = 5.0, name="Redpitaya_PhotonCounter"):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))
        self._buf = ""
        self.name = name

    # =========================================================
    # LOW LEVEL IO
    # =========================================================

    def _recv_line(self) -> Optional[str]:
        """Read one full line from socket buffer."""
        while "\n" not in self._buf:
            try:
                data = self.sock.recv(4096).decode()
                if not data:
                    return None
                self._buf += data
            except socket.timeout:
                return None

        line, self._buf = self._buf.split("\n", 1)
        return line.strip()

    def _send(self, cmd: str) -> str:
        self.sock.sendall((cmd.strip() + "\n").encode())
        line = self._recv_line()
        if line is None:
            raise TimeoutError("No response from server")
        return line

    # =========================================================
    # BASIC CONTROL
    # =========================================================

    def enable(self): self._send("ENABLE")
    def disable(self): self._send("DISABLE")
    def reset(self): self._send("RESET")

    def set_threshold(self, value: int):
        self._send(f"SET_THRESHOLD {value}")

    def set_deadtime(self, cycles: int):
        self._send(f"SET_DEADTIME {cycles}")

    def set_gate_period(self, cycles: int):
        self._send(f"SET_GATE {cycles}")

    # =========================================================
    # READOUT
    # =========================================================

    def get_count(self) -> int:
        return int(self._send("GET_COUNT"))

    def get_rate(self) -> CountRate:
        resp = self._send("GET_RATE")
        raw, cps = resp.split()
        return CountRate(int(raw), float(cps))

    def get_adc_raw(self) -> int:
        return int(self._send("GET_ADC"))

    def get_peak(self) -> int:
        return int(self._send("GET_PEAK"))

    def get_status(self) -> dict:
        resp = self._send("GET_STATUS")
        return {
            k: int(v)
            for k, v in (p.split("=") for p in resp.split())
        }

    def get_config(self) -> dict:
        resp = self._send("GET_CONFIG")
        return {
            k: int(v)
            for k, v in (p.split("=") for p in resp.split())
        }

    def get_histogram(self) -> List[int]:
        return [int(x) for x in self._send("GET_HISTOGRAM").split()]

    # =========================================================
    # STREAMING
    # =========================================================

    def start_stream(self, interval_ms: int = 500):
        self._send(f"STREAM {interval_ms}")

    def start_stream1D(self, interval_ms: int = 500):
        self._send(f"STREAM1D {interval_ms}")

    def start_stream_trig(self, interval_ms: int = 500):
        self._send(f"STREAM_TRIG {interval_ms}")

    def stop_stream(self):
        self.sock.sendall(b"STOP\n")
        self._buf = ""

    # ---------------- STREAM PARSERS ----------------

    def read_stream(self) -> Optional[Tuple[float, int, int, float]]:
        line = self._recv_line()
        if not line:
            return None

        parts = line.split()
        if parts[0] != "STREAM":
            return None

        return (float(parts[1]), int(parts[2]), int(parts[3]), float(parts[4]))

    def read_stream1D(self) -> Optional[List[Tuple[float, int, int, float]]]:
        line = self._recv_line()
        if not line:
            return None

        parts = line.split()
        if parts[0] != "STREAM1D":
            return None

        out = []
        for item in parts[1:]:
            try:
                t, c, r, cps = item.split(",")
                out.append((float(t), int(c), int(r), float(cps)))
            except ValueError:
                continue
        return out

    def read_stream_trig(self) -> Optional[Tuple[float, List[int]]]:
        line = self._recv_line()
        if not line:
            return None

        parts = line.split()
        if parts[0] != "STREAM1D":
            return None

        try:
            ts = float(parts[1])
            counts = [int(x) for x in parts[2:]]
            return ts, counts
        except ValueError:
            return None

    # =========================================================
    # TRIGGERED MODE
    # =========================================================

    def set_trig_enable(self, enable: bool):
        self._send(f"SET_TRIG_ENABLE {int(enable)}")

    def set_trig_arm(self, arm: bool):
        self._send(f"SET_TRIG_ARM {int(arm)}")

    def set_trig_total_gates(self, num: int):
        if not (1 <= num <= 1024):
            raise ValueError("num_gates must be 1..1024")
        self._send(f"SET_TRIG_TOTAL_GATES {num}")

    def set_pixels(self, num: int):
        self.set_trig_total_gates(num)

    def get_trig_status(self) -> TrigStatus:
        resp = self._send("GET_TRIG_STATUS")
        parts = dict(p.split("=") for p in resp.split())
        return TrigStatus(
            trig_active=bool(int(parts["trig_active"])),
            trig_done=bool(int(parts["trig_done"]))
        )

    def get_trig_counts(self) -> List[int]:
        return [int(x) for x in self._send("GET_TRIG_COUNTS").split()]

    def get_trig_count(self, index: int) -> int:
        return int(self._send(f"GET_TRIG_COUNT {index}"))

    def get_trig_config(self) -> dict:
        resp = self._send("GET_TRIG_CONFIG")
        return {
            k: int(v)
            for k, v in (p.split("=") for p in resp.split())
        }

    # =========================================================
    # CLEAN EXIT
    # =========================================================

    def close(self):
        try:
            self.sock.sendall(b"STOP\n")
        except Exception:
            pass
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()