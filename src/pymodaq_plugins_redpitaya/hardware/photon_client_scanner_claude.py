"""
Photon Counter Client Library — runs on your PC.

Connects to photon_server_scanner.py running on the Red Pitaya and
provides a clean Python API for photon counting.

Usage example:
    from photon_client_scanner import PhotonCounter

    with PhotonCounter("169.254.121.34") as pc:
        pc.set_threshold(200)
        pc.set_deadtime(16)
        pc.set_gate_period(1_250_000)   # 10 ms gate
        pc.enable()

        # Free-running rate
        print(pc.get_rate())

        # Non-triggered 1-D gated stream
        pc.start_stream_gated(interval_ms=10)
        for _ in range(100):
            pt = pc.read_stream_gated()
            if pt: print(pt)
        pc.stop_stream()

        # Triggered scan
        pc.set_trig_enable(True)
        pc.set_trig_total_gates(50)
        pc.set_gate_period(125_000)     # 1 ms gate
        counts = pc.scan_trig(timeout=10.0)
        print(counts)
"""

import socket
import time
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


@dataclass
class CountRate:
    raw_counts: int     # counts in last gate period
    cps: float          # counts per second
    total_count: int = 0


@dataclass
class TrigStatus:
    trig_active: bool
    trig_done: bool


@dataclass
class GatedPoint:
    timestamp: float
    gate_index: int
    raw_counts: int
    cps: float


class PhotonCounter:
    """Client for the Red Pitaya photon counter FPGA module."""

    def __init__(self, host: str = '169.254.121.34', port: int = 5555,
                 timeout: float = 5.0, name: str = "Redpitaya_PhotonCounter"):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._timeout = timeout
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))
        self._buf = ""
        self.name = name

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------
    def _send(self, cmd: str) -> str:
        """Send one command line and return the response line."""
        self.sock.sendall((cmd.strip() + "\n").encode())
        while "\n" not in self._buf:
            data = self.sock.recv(4096).decode(errors="replace")
            if not data:
                raise ConnectionError("Server closed connection")
            self._buf += data
        line, self._buf = self._buf.split("\n", 1)
        line = line.strip()
        if line.startswith("ERR"):
            raise RuntimeError(f"Server error: {line}")
        return line

    def _recv_line(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Non-blocking read of one line from the socket.
        Returns None if no complete line is available within timeout.
        """
        deadline = time.perf_counter() + (timeout or 0)
        self.sock.settimeout(timeout or 0.001)
        try:
            while "\n" not in self._buf:
                try:
                    data = self.sock.recv(4096).decode(errors="replace")
                    if not data:
                        return None
                    self._buf += data
                except socket.timeout:
                    if time.perf_counter() > deadline:
                        return None
            line, self._buf = self._buf.split("\n", 1)
            return line.strip()
        finally:
            self.sock.settimeout(self._timeout)

    # ------------------------------------------------------------------
    # Basic control
    # ------------------------------------------------------------------
    def enable(self) -> None:
        """Enable pulse counting."""
        self._send("ENABLE")

    def disable(self) -> None:
        """Disable pulse counting."""
        self._send("DISABLE")

    def reset(self) -> None:
        """Reset all counters and histogram."""
        self._send("RESET")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def set_threshold(self, value: int) -> None:
        """Set detection threshold in signed ADC units (16-bit).
        At ±20 V range: 1 LSB ≈ 2.44 mV.  E.g. 200 ≈ 488 mV.
        """
        self._send(f"SET_THRESHOLD {value}")

    def set_deadtime(self, cycles: int) -> None:
        """Set dead time in 125 MHz clock cycles (1 cycle = 8 ns)."""
        self._send(f"SET_DEADTIME {cycles}")

    def set_gate_period(self, cycles: int) -> None:
        """Set gate period in clock cycles.
        125_000_000 = 1 s,  12_500_000 = 100 ms,  1_250_000 = 10 ms.
        """
        self._send(f"SET_GATE {cycles}")

    def set_hist_shift(self, shift: int) -> None:
        """Set histogram bin shift (0–5).  bin = (peak >> shift) & 0x3F."""
        self._send(f"SET_HIST_SHIFT {shift}")

    # ------------------------------------------------------------------
    # Scalar readbacks
    # ------------------------------------------------------------------
    def get_count(self) -> int:
        """Cumulative pulse count since last reset."""
        return int(self._send("GET_COUNT"))

    def get_rate(self) -> CountRate:
        """Count rate: raw counts in last gate + CPS."""
        parts = self._send("GET_RATE").split()
        return CountRate(raw_counts=int(parts[0]), cps=float(parts[1]))

    def get_adc_raw(self) -> int:
        """Current ADC sample (signed, useful for threshold tuning)."""
        return int(self._send("GET_ADC"))

    def get_peak(self) -> int:
        """Peak ADC value from the most recent pulse."""
        return int(self._send("GET_PEAK"))

    def get_status(self) -> dict:
        """Full status dict: enabled, overflow, count, rate."""
        return self._parse_kv(self._send("GET_STATUS"))

    def get_config(self) -> dict:
        """Current configuration dict."""
        return self._parse_kv(self._send("GET_CONFIG"))

    def get_histogram(self) -> List[int]:
        """64-bin pulse height histogram."""
        return [int(x) for x in self._send("GET_HISTOGRAM").split()]

    # ------------------------------------------------------------------
    # Triggered mode configuration
    # ------------------------------------------------------------------
    def set_trig_enable(self, enable: bool) -> None:
        """Enable or disable hardware-triggered gated counting mode."""
        self._send(f"SET_TRIG_ENABLE {int(enable)}")

    def set_trig_arm(self) -> None:
        """Arm the trigger for the next scan.
        The server always generates a clean 0→1 rising edge in hardware.
        """
        self._send("SET_TRIG_ARM")

    def set_trig_total_gates(self, num_gates: int) -> None:
        """Number of gate windows per triggered scan (1–1024)."""
        if num_gates < 1 or num_gates > 1024:
            raise ValueError("num_gates must be 1–1024")
        self._send(f"SET_TRIG_TOTAL_GATES {num_gates}")

    # Alias for scanner-style usage
    def set_pixels(self, n: int) -> None:
        self.set_trig_total_gates(n)

    def get_trig_status(self) -> TrigStatus:
        """Return TrigStatus(trig_active, trig_done)."""
        d = self._parse_kv(self._send("GET_TRIG_STATUS"))
        return TrigStatus(trig_active=bool(int(d["trig_active"])),
                          trig_done=bool(int(d["trig_done"])))

    def get_trig_counts(self) -> List[int]:
        """Read back all N gate counts as a list (blocking, no timeout)."""
        return [int(x) for x in self._send("GET_TRIG_COUNTS").split()]

    def get_trig_count(self, index: int) -> int:
        """Read back a single gate count by index."""
        if index < 0 or index >= 1024:
            raise ValueError("index must be 0–1023")
        return int(self._send(f"GET_TRIG_COUNT {index}"))

    def get_trig_config(self) -> dict:
        """Current triggered-mode configuration dict."""
        return self._parse_kv(self._send("GET_TRIG_CONFIG"))

    # ------------------------------------------------------------------
    # Convenience: blocking triggered scan
    # ------------------------------------------------------------------
    # def scan_trig(self, timeout: float = 10.0,
    #               poll_interval: float = 0.01) -> List[int]:
    #     """
    #     Arm the trigger, poll until trig_done, return all gate counts.
    #
    #     This is the simplest way to do a triggered scan without streaming.
    #     The FPGA must already be configured (trig_enable, total_gates,
    #     gate_period) before calling this.
    #
    #     Returns a list of N integers (counts per gate window).
    #     Raises TimeoutError if no trigger arrives within `timeout` seconds.
    #     """
    #     self.set_trig_arm()
    #     deadline = time.perf_counter() + timeout
    #     while time.perf_counter() < deadline:
    #         status = self.get_trig_status()
    #         if status.trig_done:
    #             return self.get_trig_counts()
    #         time.sleep(poll_interval)
    #     raise TimeoutError(f"scan_trig: no trigger received within {timeout} s")

    def scan_trig(self, timeout=10.0, poll_interval=0.1):
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_trig_status()
            if status.trig_done:
                try:
                    return self.get_trig_counts()
                except ConnectionError:
                    # Drain the socket buffer
                    self.sock.settimeout(0.1)
                    try:
                        while True:
                            data = self.sock.recv(4096)
                            if not data:
                                break
                    except socket.timeout:
                        pass
                    self.sock.settimeout(10.0)
                    continue
            time.sleep(poll_interval)
        raise TimeoutError("Triggered scan timed out")


    # ------------------------------------------------------------------
    # Streaming: STREAM  (continuous rate)
    # ------------------------------------------------------------------
    def start_stream(self, interval_ms: int = 500) -> None:
        """Start continuous rate streaming.  Read with read_stream()."""
        self._send(f"STREAM {interval_ms}")

    def read_stream(self) -> Optional[Tuple[float, int, int, float]]:
        """
        Read one STREAM data point.
        Returns (timestamp, total_count, gate_count, cps) or None on timeout.
        """
        line = self._recv_line(timeout=0.05)
        if line is None:
            return None
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "STREAM":
            return (float(parts[1]), int(parts[2]), int(parts[3]), float(parts[4]))
        return None

    # ------------------------------------------------------------------
    # Streaming: STREAM_GATED  (free-running 1-D, no trigger needed)
    # ------------------------------------------------------------------
    def start_stream_gated(self, interval_ms: int = 100) -> None:
        """
        Start free-running gated 1-D streaming.
        The server emits one line per completed gate window using count_rate.
        No hardware trigger is needed.
        Read with read_stream_gated().
        """
        self._send(f"STREAM_GATED {interval_ms}")

    def read_stream_gated(self) -> Optional[GatedPoint]:
        """
        Read one STREAM_GATED data point.
        Returns GatedPoint(timestamp, gate_index, raw_counts, cps) or None.
        """
        line = self._recv_line(timeout=0.5)
        if line is None:
            return None
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "STREAM_GATED":
            return GatedPoint(timestamp=float(parts[1]),
                              gate_index=int(parts[2]),
                              raw_counts=int(parts[3]),
                              cps=float(parts[4]))
        return None

    # ------------------------------------------------------------------
    # Streaming: STREAM_TRIG  (triggered scan, returns all gates at once)
    # ------------------------------------------------------------------
    def start_stream_trig(self, timeout_s: float = 10.0) -> None:
        """
        Arm and start triggered scan streaming.
        The server arms the trigger, waits for trig_done, then emits a
        single STREAM_TRIG line containing all N gate counts.
        Read the result with read_stream_trig().
        """
        self._send(f"STREAM_TRIG {timeout_s}")

    def read_stream_trig(self, timeout: float = 15.0) -> Optional[Tuple[float, List[int]]]:
        """
        Block until the STREAM_TRIG result line arrives.
        Returns (timestamp, [count_gate_0, count_gate_1, ...]) or None.
        Raises RuntimeError on server-side timeout.
        """
        line = self._recv_line(timeout=timeout)
        if line is None:
            return None
        if line.startswith("ERR"):
            raise RuntimeError(line)
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "STREAM_TRIG":
            return (float(parts[1]), [int(x) for x in parts[2:]])
        return None

    # ------------------------------------------------------------------
    # Stop any stream
    # ------------------------------------------------------------------
    def stop_stream(self) -> None:
        """Stop any active stream and drain pending data."""
        self.sock.sendall(b"STOP\n")
        self.sock.settimeout(0.2)
        try:
            while True:
                if not self.sock.recv(4096):
                    break
        except socket.timeout:
            pass
        finally:
            self.sock.settimeout(self._timeout)
        self._buf = ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_kv(resp: str) -> dict:
        """Parse 'key=value key=value ...' into a dict of strings."""
        result = {}
        for pair in resp.split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                result[k] = v
        return result

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self.stop_stream()
        except Exception:
            pass
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
