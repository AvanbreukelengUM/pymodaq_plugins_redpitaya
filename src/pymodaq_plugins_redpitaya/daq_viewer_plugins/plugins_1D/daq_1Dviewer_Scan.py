from qtpy.QtCore import QThread

from pymodaq.utils.data import DataFromPlugins, Axis, DataToExport
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.parameter import Parameter
from pymodaq_plugins_redpitaya.utils import Config
from collections import deque
import time
import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins
from pymeasure.instruments.redpitaya.redpitaya_scpi import RedPitayaScpi, AnalogOutputFastChannel
from pymodaq_plugins_redpitaya.hardware.photon_client_scanner import PhotonScanner

class DAQ_1DViewer_Scan(DAQ_Viewer_base):
    """ Instrument plugin class for a 1D viewer.
    
    This object inherits all functionalities to communicate with PyMoDAQ’s DAQ_Viewer module through
    inheritance via DAQ_Viewer_base. It makes a bridge between the DAQ_Viewer module and the
    Python wrapper of a particular instrument.

    * Should be compatible with all redpitaya flavour using the SCPI communication protocol
    * Tested with the STEMlab 125-14 Pro (Gen 2) version
    * PyMoDAQ >= 4.1.0

    Attributes:
    -----------
    controller: object
        The particular object that allow the communication with the hardware, in general a python wrapper around the
         hardware library.

    """
    plugin_config = Config()

    params = comon_parameters+[
        {'title': 'IP Address:', 'name': 'ip_address', 'type': 'str',
         'value': plugin_config('ip_address')},
        {'title': 'Port:', 'name': 'port', 'type': 'int', 'value': plugin_config('port')},
        {'title': 'Board name:', 'name': 'bname', 'type': 'str', 'readonly': True},

        {'title': 'Counting:', 'name': 'counting', 'type': 'group', 'children': [
            {'title': 'Port:', 'name': 'port_count', 'type': 'int',
              'value': plugin_config('counting', 'port_scan')},
            {'title': 'Threshold (ADC units):', 'name': 'threshold', 'type': 'int',
             'value': plugin_config('counting', 'threshold')},
            {'title': 'Deadtime (clock cycles, 1=8ns):', 'name': 'deadtime', 'type': 'int',
             'value': plugin_config('counting', 'deadtime')},
            {'title': 'Gate period (ms):', 'name': 'gate_ms', 'type': 'int',
             'value': plugin_config('counting', 'gate_ms')},
            # {'title': 'Stream update (ms):', 'name': 'stream_ms', 'type': 'int',
            #  'value': plugin_config('counting', 'stream_ms')},
            # {'title': 'Histogram:', 'name': 'histogram', 'type': 'bool',
            #  'value': plugin_config('counting', 'histogram')},
        ]},
        {'title': 'Scanning:', 'name': 'scan', 'type': 'group', 'children': [
            {'title': 'Resolution (number of pixels):', 'name': 'res', 'type': 'int',
             'value': plugin_config('scan', 'res')},
            {'title': 'Start (μm)', 'name': 'start', 'type': 'float',
             'value': plugin_config('scan', 'start')},
            {'title': 'Stop (μm)', 'name': 'stop', 'type': 'float',
             'value': plugin_config('scan', 'stop')},
            {'title': 'Stop (μm)', 'name': 'stop', 'type': 'float',
             'value': plugin_config('scan', 'stop')},
            {'title': 'Shape', 'name': 'shape', 'type': 'list',
             'limits': AnalogOutputFastChannel.SHAPES, 'value': plugin_config('scan', 'shape')},
        ]},
        ]

    def ini_attributes(self):
        self.controller: PhotonScanner = None
        self.mover: RedPitayaScpi = None
        self.x_axis: Axis = None
        # self.history = int(self.settings['counting', 'stream_ms'] / self.settings['counting', 'gate_ms'])
        # self.times = deque(maxlen=self.settings['counting', 'deadtime'])
        # self.rates = deque(maxlen=self.history)
        # self.t0 = time.time()
        self.t0 =1777990705
        self.cps = 0


    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == 'threshold':
            self.controller.set_threshold(param.value())
            print(f"  Threshold: {param.value()} ADC units")

        elif param.name() == 'deadtime':
            self.controller.set_deadtime(param.value())
            print(f"  Dead time: {param.value()} cycles ({param.value() * 8} ns)")

        elif param.name() == 'gate_ms':
            gate_cycles = int(param.value()*125_000)
            self.controller.set_gate_period(gate_cycles)
            print(f"  Gate period: {param.value()} ms ({gate_cycles} cycles)")
            self.history = int(self.settings['counting', 'stream_ms'] / param.value())
            self.times = deque(maxlen=self.history)
            self.rates = deque(maxlen=self.history)
            if 1 / param.value() * 1000 > self.cps:
                print("WARNING: Gate period might be too short for the current count rate.")
            if param.value() < 10:
                print("Attention: Gate period is lower than the PyMoDAQ update time.")

        # elif param.name() == 'stream_ms':
        #     self.controller.stop_stream()
        #     self.history = int(param.value()/self.settings['counting', 'gate_ms'])
        #     self.times = deque(maxlen=self.history)
        #     self.rates = deque(maxlen=self.history)
        #     print(self.history)
        #     self.controller.start_stream1D(param.value())
        #     print(f"  Restarted stream: {param.value()} ms")

        elif param.name() == 'res':
            self.controller.set_pixels(param.value())

        # elif param.name() == 'start':
        #     self.mover.

        elif param.name() == 'stop':
            setattr(self.aout, 'amplitude', param.value())


    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """

        self.ini_detector_init(old_controller=controller,
                               new_controller=PhotonScanner(host=self.settings['ip_address'],
                                                            port=self.settings['counting','port_count']))
        bname = self.controller.name
        self.settings.child('bname').setValue(bname)

        self.controller.reset()
        self.controller.set_threshold(self.settings['counting', 'threshold'])
        self.controller.set_deadtime(self.settings['counting', 'deadtime'])
        gate_cycles = int(self.settings['counting', 'gate_ms'] * 125_000)
        self.controller.set_gate_period(gate_cycles)
        self.controller.enable()
        self.controller.start_stream1D(self.settings['counting', 'stream_ms'])

        info = f"Succesfully connected to the Redpitaya {bname} board"
        initialized = True
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        self.controller.stop_stream()
        self.controller.disable()
        self.controller.close()
        self.aout.enable = False

    def aout(self):
        """ It defines what output channel the user chose"""
        return self.mover.analog_out[1]

    def grab_data(self, Naverage=1, **kwargs):

        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble, and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """
        # QThread.msleep(max((1, int(self.settings['counting', 'stream_ms']))))
        points = self.controller.read_stream1D()
        if points:
            for point in points:
                ts, total, gate_count, self.cps = point
                # t = ts - self.t0 if self.t0 else 0
                self.times.append(ts)
                self.rates.append(self.cps)

        else:
            print("No data. Re-trying...")

        scaling =   (self.times[-1]-self.times[0])/(np.size(self.rates))

        axis = Axis('time', units='s', offset=0,
                    scaling=scaling,
                    size=np.size(self.rates))
        self.dte_signal.emit(DataToExport('PhotonCounter',
                                              data=[DataFromPlugins(name='RedPitaya', data=[np.array(self.rates)],
                                                                dim='Data1D', labels=['IN1'],
                                                                    axes=[axis])]))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        # self.controller.stop_stream()
        return ''


if __name__ == '__main__':
    main(__file__, init=False)
