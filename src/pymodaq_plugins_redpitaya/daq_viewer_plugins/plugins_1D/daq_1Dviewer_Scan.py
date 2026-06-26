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
# from pymodaq_plugins_redpitaya.hardware.photon_client_scanner import PhotonScanner
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

    params = comon_parameters + [
        {'title': 'IP Address:', 'name': 'ip_address', 'type': 'str',
         'value': plugin_config('ip_address')},
        {'title': 'Port:', 'name': 'port', 'type': 'int', 'value': plugin_config('port')},
        {'title': 'Board name:', 'name': 'bname', 'type': 'str', 'readonly': True},

        {'title': 'Counting:', 'name': 'counting', 'type': 'group', 'children': [
            {'title': 'Port:', 'name': 'port_count', 'type': 'int',
             'value': plugin_config('scan', 'port_scan')},
            {'title': 'Threshold (ADC units):', 'name': 'threshold', 'type': 'int',
             'value': plugin_config('counting', 'threshold')},
            {'title': 'Deadtime (clock cycles, 1=8ns):', 'name': 'deadtime', 'type': 'int',
             'value': plugin_config('counting', 'deadtime')},
            {'title': 'Gate period (ms):', 'name': 'gate_ms', 'type': 'int',
             'value': plugin_config('counting', 'gate_ms')},
        ]},

        {'title': 'Scanning:', 'name': 'scan', 'type': 'group', 'children': [
            {'title': 'Resolution (number of pixels):', 'name': 'res', 'type': 'int',
             'value': plugin_config('scan', 'res'), 'limits': (1, 1024)},
            {'title': 'Start (μm)', 'name': 'start', 'type': 'float',
             'value': plugin_config('scan', 'start')},
            {'title': 'Stop (μm)', 'name': 'stop', 'type': 'float',
             'value': plugin_config('scan', 'stop')},
            # {'title': 'Shape', 'name': 'shape', 'type': 'list',
            #  'limits': AnalogOutputFastChannel.SHAPES, 'value': plugin_config('scan', 'shape')},
            {'title': 'Conversion [μm/V]', 'name': 'conversion', 'type': 'float', 'limits': (-1e-4, 1e3),
             'value': plugin_config('Scaling', 'scaling')},
        ]},
    ]

    def ini_attributes(self):
        self.controller: PhotonScanner = None
        self.mover: RedPitayaScpi = None
        self.x_axis: Axis = None

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
            gate_cycles = int(param.value() * 125_000)
            self.controller.set_gate_period(gate_cycles)
            print(f"  Gate period: {param.value()} ms ({gate_cycles} cycles)")
            if 1 / param.value() * 1000 > self.gated_rates[0]:
                print("WARNING: Gate period might be too short for the current count rate.")
            if param.value() * self.settings['scan', 'res'] < 10:
                print("Attention: Gate period is lower than the PyMoDAQ update time.")
            self.mover.analog_out[1].frequency = 1000 / param.value() / self.settings['scan', 'res']


        elif param.name() == 'res':
            self.controller.set_pixels(param.value())
            self.mover.analog_out[1].frequency = 1000 / param.value() / self.settings[
                'counting', 'gate_ms']


        elif param.name() == 'start':
            self.stop = self.settings['scan', 'stop'] / self.settings['scan', 'conversion'] - 2
            self.start = param.value() / self.settings['scan', 'conversion'] - 2
            self.mover.analog_out[1].waveform_data = np.linspace(start, stop, 16384)


        elif param.name() == 'stop':
            self.start = self.settings['scan', 'start'] / self.settings['scan', 'conversion'] - 2
            self.stop = param.value() / self.settings['scan', 'conversion'] - 2
            self.mover.analog_out[1].waveform_data = np.linspace(start, stop, 16384)


        elif param.name() == 'conversion':
            self.start = self.settings['scan', 'start'] / param.value() - 2
            self.stop = self.settings['scan', 'stop'] / param.value() - 2
            self.mover.analog_out[1].waveform_data = np.linspace(start, stop, 16384)
            self.mover.analog_out[1].burst_initial_voltage = self.start
            self.mover.analog_out[1].burst_last_voltage = self.stop

    @property
    def aout(self):
        """ It defines what output channel the user chose"""
        return self.mover.analog_out[1]

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
                                                            port=self.settings['counting', 'port_count']))
        self.mover = RedPitayaScpi(ip_address=self.settings['ip_address'], port=self.settings['port'])
        bname = self.controller.name
        self.settings.child('bname').setValue(bname)

        self.controller.reset()
        self.controller.set_threshold(self.settings['counting', 'threshold'])
        self.controller.set_deadtime(self.settings['counting', 'deadtime'])
        gate_cycles = int(self.settings['counting', 'gate_ms'] * 125_000)
        self.controller.set_gate_period(gate_cycles)

        self.mover.output_reset()
        self.mover.analog_out[1].shape = "ARBITRARY"  # plugin_config('generator', 'shape')
        # self.settings.child('bounds', 'is_bounds').setOpts(readonly=True)
        self.mover.analog_out[1].burst_mode = "BURST"
        self.start = self.settings['scan', 'start'] / self.settings['scan', 'conversion'] - 2
        self.stop = self.settings['scan', 'stop'] / self.settings['scan', 'conversion'] - 2
        x = np.linspace(self.start, self.stop, 16384)
        waveform = []
        for n in x:
            waveform.append(f"{n:.5f}")
        waveform1 = ", ".join(map(str, waveform))
        self.mover.analog_out[1].waveform_data = waveform1
        self.mover.analog_out[1].frequency = 1000 / self.settings['scan', 'res'] / self.settings['counting', 'gate_ms']
        self.mover.analog_out[1].offset = 0
        self.mover.analog_out[1].burst_initial_voltage = self.start
        self.mover.analog_out[1].burst_last_voltage = self.stop
        self.mover.analog_out[1].burst_num_cycles = 1
        self.mover.analog_out[1].burst_num_repetitions = 1
        self.mover.analog_out[1].enable = True

        self.controller.enable()
        self.controller.set_pixels(self.settings['scan', 'res'])
        self.gated_rates = np.zeros(self.settings['scan', 'res'])
        self.controller.trig_soft(False)
        # self.controller.start_stream_trig(int(self.settings['counting', 'gate_ms'] * self.settings['scan', 'res']))

        info = f"Succesfully connected to the Redpitaya {bname} board"
        initialized = True
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        self.controller.disable()
        self.controller.trig_soft(False)
        self.controller.close()
        self.mover.output_reset()
        self.mover.analog_out[1].enable = False

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
        self.mover.analog_out[1].burst_initial_voltage = self.start
        self.mover.analog_out[1].burst_last_voltage = self.stop

        self.mover.analog_out[1].run()

        while True:
            status = self.controller.get_trig_status()
            if status.trig_done:
                break
        points = self.controller.get_trig_rates()
        if points:
            self.gated_rates = np.array(points)
        else:
            print("No data. Re-trying...")

        scaling = self.settings['counting', 'gate_ms'] / 1000
        axis = Axis('time', units='s', offset=0,
                    scaling=scaling,
                    size=np.size(self.gated_rates))

        self.dte_signal.emit(DataToExport('PhotonScanner',
                                          data=[DataFromPlugins(name='RedPitaya', data=[self.gated_rates],
                                                                dim='Data1D', labels=['IN1'], units='cps',
                                                                axes=[axis])]))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.controller.disable()
        return ''


if __name__ == '__main__':
    main(__file__, init=True)