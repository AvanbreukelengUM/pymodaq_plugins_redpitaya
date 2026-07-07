from pymodaq.scripting import Detector
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
             'value': plugin_config('scan', 'res'), 'limits': (1, PhotonScanner.MAX_TRIG_GATES)},
            {'title': 'Start (μm)', 'name': 'start', 'type': 'float',
             'value': plugin_config('scan', 'start')},
            {'title': 'Finish (μm)', 'name': 'finish', 'type': 'float',
             'value': plugin_config('scan', 'stop')},
            # {'title': 'Shape', 'name': 'shape', 'type': 'list',
            #  'limits': AnalogOutputFastChannel.SHAPES, 'value': plugin_config('scan', 'shape')},
            {'title': 'Conversion [μm/V]', 'name': 'conversion', 'type': 'float', 'limits': (-1e-4, 1e3),
             'value': plugin_config('Scaling', 'scaling')},
            {'title': 'Backforce', 'name': 'backforce', 'type': 'bool',
             'value': 'true','tip':'Choose this option if you want to alternate right with left handed scans'},
        ]},
    ]

    def ini_attributes(self):
        self.detector: PhotonScanner = None
        self.controller: RedPitayaScpi = None
        self.x_axis: Axis = None
        self.backforce: bool = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == 'threshold':
            self.detector.set_threshold(param.value())
            print(f"  Threshold: {param.value()} ADC units")

        elif param.name() == 'deadtime':
            self.detector.set_deadtime(param.value())
            print(f"  Dead time: {param.value()} cycles ({param.value() * 8} ns)")

        elif param.name() == 'gate_ms':
            gate_cycles = int(param.value() * 125_000)
            self.detector.set_gate_period(gate_cycles)
            print(f"  Gate period: {param.value()} ms ({gate_cycles} cycles)")
            if 1 / param.value() * 1000 > self.gated_rates[0]:
                print("WARNING: Gate period might be too short for the current count rate.")
            if param.value() * self.settings['scan', 'res'] < 10:
                print("Attention: Gate period is lower than the PyMoDAQ update time.")
            self.controller.analog_out[1].frequency = 1000 / param.value() / self.settings['scan', 'res']


        elif param.name() == 'res':
            self.detector.set_pixels(param.value())
            self.controller.analog_out[1].frequency = 1000 / param.value() / self.settings[
                'counting', 'gate_ms']


        elif param.name() == 'start':
            self.finish = self.settings['scan', 'finish'] / self.settings['scan', 'conversion'] - 2
            self.start = param.value() / self.settings['scan', 'conversion'] - 2
            self.controller.analog_out[1].waveform_data = np.linspace(self.start, self.finish, 16384)


        elif param.name() == 'finish':
            self.start = self.settings['scan', 'start'] / self.settings['scan', 'conversion'] - 2
            self.finish = param.value() / self.settings['scan', 'conversion'] - 2
            self.controller.analog_out[1].waveform_data = np.linspace(self.start, self.finish, 16384)


        elif param.name() == 'conversion':
            self.start = self.settings['scan', 'start'] / param.value() - 2
            self.finish = self.settings['scan', 'finish'] / param.value() - 2
            self.controller.analog_out[1].waveform_data = np.linspace(self.start, self.finish, 16384)
            self.controller.analog_out[1].burst_initial_voltage = self.start
            self.controller.analog_out[1].burst_last_voltage = self.finish

        elif param.name() == 'backforce':
            self.backforce = True

    @property
    def aout(self):
        """ It defines what output channel the user chose"""
        return self.controller.analog_out[1]

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

        # self.ini_detector_init(old_controller=controller,
        #                        new_controller=PhotonScanner(host=self.settings['ip_address'],
        #                                                     port=self.settings['counting', 'port_count']))
        if self.is_master:  # is needed when controller is master
            self.controller = RedPitayaScpi(ip_address=self.settings['ip_address'], port=self.settings['port']) #  arguments for instantiation!)
            # self.detector = RedPitayaScpi(ip_address=plugin_config('ip_address')) #  arguments for instantiation!)
        else:
            self.controller = controller

        self.detector = PhotonScanner(host=self.settings['ip_address'],
                                      port=self.settings['counting', 'port_count'])
        bname = self.detector.name
        self.settings.child('bname').setValue(bname)

        self.detector.reset()
        self.detector.set_threshold(self.settings['counting', 'threshold'])
        self.detector.set_deadtime(self.settings['counting', 'deadtime'])
        gate_cycles = int(self.settings['counting', 'gate_ms'] * 125_000)
        self.detector.set_gate_period(gate_cycles)

        self.controller.output_reset()
        self.controller.analog_out[1].shape = "ARBITRARY"  # plugin_config('generator', 'shape')
        # self.settings.child('bounds', 'is_bounds').setOpts(readonly=True)
        self.controller.analog_out[1].burst_mode = "BURST"
        self.start = self.settings['scan', 'start'] / self.settings['scan', 'conversion'] - 2
        self.finish = self.settings['scan', 'finish'] / self.settings['scan', 'conversion'] - 2
        self.backforce = self.settings['scan', 'backforce']
        x = np.linspace(self.start, self.finish, 16384)
        waveform = []
        for n in x:
            waveform.append(f"{n:.5f}")
        self.waveform1 = ", ".join(map(str, waveform))
        self.waveform_backforce = ", ".join(map(str, reversed(waveform)))
        self.i =0
        self.controller.analog_out[1].waveform_data = self.waveform1
        self.controller.analog_out[1].frequency = 1000 / self.settings['scan', 'res'] / self.settings['counting', 'gate_ms']
        self.controller.analog_out[1].offset = 0
        self.controller.analog_out[1].burst_initial_voltage = self.start
        self.controller.analog_out[1].burst_last_voltage = self.finish
        self.controller.analog_out[1].burst_num_cycles = 1
        self.controller.analog_out[1].burst_num_repetitions = 1
        self.controller.analog_out[1].enable = True

        self.detector.enable()
        self.detector.set_pixels(self.settings['scan', 'res'])
        self.gated_rates = np.zeros(self.settings['scan', 'res'])
        self.detector.trig_soft(False)
        # self.detector.start_stream_trig(int(self.settings['counting', 'gate_ms'] * self.settings['scan', 'res']))

        info = f"Succesfully connected to the Redpitaya {bname} board"
        initialized = True
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        self.detector.disable()
        self.detector.trig_soft(False)
        self.detector.close()
        self.controller.output_reset()
        self.controller.analog_out[1].enable = False

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
        self.detector.enable()
        self.controller.analog_out[1].run()
        QThread.msleep(self.settings['counting', 'gate_ms'])
        while True:
            status = self.detector.get_trig_status()
            if status.trig_done:
                self.detector.disable()
                break
        points = self.detector.get_trig_rates()
        # points = self.detector.get_trig_rates_debug()

        if points:
            self.gated_rates = np.array(points)
            print(self.gated_rates)
        else:
            print("No data. Re-trying...")

        scaling = self.settings['counting', 'gate_ms'] / 1000
        axis = Axis('time', units='s', offset=0,
                    scaling=scaling,
                    size=np.size(self.gated_rates))

        if self.backforce:
            self.i = self.i + 1
        if self.i%2:
            # For the next cycle we go left-way
            self.controller.analog_out[1].waveform_data = self.waveform_backforce
            self.controller.analog_out[1].burst_initial_voltage = self.finish
            self.controller.analog_out[1].burst_last_voltage = self.start
        else:
            self.gated_rates = reversed(self.gated_rates)
            # For the next cycle we go right-way
            self.controller.analog_out[1].waveform_data = self.waveform1
            self.controller.analog_out[1].burst_initial_voltage = self.start
            self.controller.analog_out[1].burst_last_voltage = self.finish

        self.dte_signal.emit(DataToExport('PhotonScanner',
                                          data=[DataFromPlugins(name='RedPitaya', data=[self.gated_rates],
                                                                dim='Data1D', labels=['IN1'], units='cps',
                                                                axes=[axis])]))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        # self.detector.disable()
        return ''


if __name__ == '__main__':
    main(__file__, init=False)