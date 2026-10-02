import numpy as np
from hatch.cli.config import set_value
from qtpy import QtWidgets
from qtpy.QtCore import QThread

from pymodaq.utils.daq_utils import ThreadCommand
from pymodaq.utils.data import DataFromPlugins, Axis, DataToExport
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.parameter import Parameter

from pymodaq_plugins_redpitaya.daq_viewer_plugins.plugins_1D.daq_1Dviewer_RedPitayaSCPI import \
    DAQ_1DViewer_RedPitayaSCPI

from pymodaq_plugins_redpitaya.utils import Config

plugin_config = Config()

from pymeasure.instruments.redpitaya.redpitaya_scpi import RedPitayaScpi, AnalogOutputFastChannel


class DAQ_1DViewer_Sweep(DAQ_1DViewer_RedPitayaSCPI):
    """ Instrument plugin class for a 1D viewer.

    This object inherits all functionalities to communicate with PyMoDAQ’s DAQ_Viewer module through inheritance via
    DAQ_Viewer_base. It makes a bridge between the DAQ_Viewer module and the Python wrapper of a particular instrument.

    TODO Complete the docstring of your plugin with:
        * The set of instruments that should be compatible with this instrument plugin.
        * With which instrument it has actually been tested.
        * The version of PyMoDAQ during the test.
        * The version of the operating system.
        * Installation instructions: what manufacturer’s drivers should be installed to make it run?

    Attributes:
    -----------
    controller: object
        The particular object that allow the communication with the hardware, in general a python wrapper around the
         hardware library.

    """
    params = DAQ_1DViewer_RedPitayaSCPI.params + [
    {'title': 'Analog Output:', 'name': 'output', 'type': 'group', 'children': [
        {'title': 'AO Channel', 'name': 'aout_channel', 'type': 'list', 'limits': {'1': 1, '2': 2}},

        {'title': 'Amplitude', 'name': 'amplitude', 'type': 'float', 'limits': AnalogOutputFastChannel.AMPLITUDES,
         'value': plugin_config('generator', 'amplitude')},
        {'title': 'Enable', 'name': 'enable', 'type': 'bool', 'value': False},
        {'title': 'Shape', 'name': 'shape', 'type': 'list',
         'limits': AnalogOutputFastChannel.SHAPES, 'value': plugin_config('generator', 'shape')},
        {'title': 'Offset', 'name': 'offset', 'type': 'float', 'limits': AnalogOutputFastChannel.OFFSETS,
         'value': plugin_config('generator', 'offset')},
        {'title': 'Phase', 'name': 'phase', 'type': 'float', 'limits': AnalogOutputFastChannel.PHASES,
         'value': plugin_config('generator', 'phase')},
        {'title': 'Sweep Mode', 'name': 'sweep_mode', 'type': 'list', 'limits': AnalogOutputFastChannel.SWEEP_MODES,
         'value': plugin_config('sweep', 'sweep_modes')},
        {'title': 'Sweep Start Frequency', 'name': 'sweep_start_frequency', 'type': 'float',
         'limits': AnalogOutputFastChannel.FREQUENCIES,
         'value': plugin_config('sweep', 'sweep_start_frequency')},
        {'title': 'Sweep Stop Frequency', 'name': 'sweep_stop_frequency', 'type': 'float',
         'limits': AnalogOutputFastChannel.FREQUENCIES,
         'value': plugin_config('sweep', 'sweep_stop_frequency')},
        {'title': 'Sweep Time (µs)', 'name': 'sweep_time', 'type': 'int',
         'limits': [int(t) for t in AnalogOutputFastChannel.TIME],
         'value': plugin_config('sweep', 'sweep_time'), 'readonly': False},
        {'title': 'Sweep State', 'name': 'sweep_state', 'type': 'bool', 'value': False},
        {'title': 'Sweep Direction', 'name': 'sweep_direction', 'type': 'list', 'limits': AnalogOutputFastChannel.DIRECTION,
         'value': plugin_config('sweep', 'direction')},
    ]},
    ]

    def ini_attributes(self):
        self.controller: RedPitayaScpi = None
        self.x_axis = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        super().commit_settings(param)

        if param.name() == 'amplitude':
            self.aout.amplitude = param.value()
        elif param.name() == 'enable':
            self.aout.enable = param.value()
        elif param.name() == 'shape':
            self.aout.shape = param.value()
        elif param.name() == 'offset':
            self.aout.offset = param.value()
        elif param.name() == 'phase':
            self.aout.phase = param.value()
        elif param.name() == 'sweep_mode':
            self.aout.sweep_mode = param.value()
        elif param.name() == 'sweep_start_frequency':
            self.aout.sweep_start_frequency = param.value()
        elif param.name() == 'sweep_stop_frequency':
            self.aout.sweep_stop_frequency = param.value()
        elif param.name() in ('decimation', 'nsamples'):
            stime = int(self.settings['sampling', 'nsamples'] / self.settings['sampling', 'sample_rate'] * 1e6)
            if stime < self.aout.TIME[0]:
                self.emit_status(ThreadCommand("Update_Status",
                                               [f'The sweep time cannot be smaller than {self.aout.TIME[0]} us', 'log']))
                stime = self.aout.TIME[0]
            self.aout.sweep_time = stime
            self.settings.child('output', 'sweep_time').setValue(stime)
        elif param.name() == 'sweep_state':
            self.aout.sweep_state = param.value()
        elif param.name() == 'sweep_direction':
            self.aout.sweep_direction = param.value()

    def ini_detector(self, controller=None):
        info, initialized = super().ini_detector(controller)
        for child in self.settings.child('output').children():
            self.commit_settings(child)
        self.settings.child('sampling','decimation').setValue(plugin_config('sweep', 'sweep_decimation'))
        self.settings.child('sampling','nsamples').setValue(plugin_config('sweep', 'sweep_nsamples'))
        self.settings.child('triggering', 'center_trigger').setValue(False)
        return info, initialized

    @property
    def aout(self):
        """ It defines what output channel the user chose"""
        return self.controller.analog_out[self.settings['output', 'aout_channel']]


    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """

        nsamples = self.settings['sampling', 'nsamples']
        wait_time = nsamples / self.controller.CLOCK * self.settings['sampling', 'decimation']

        if self.settings['triggering', 'center_trigger']:
            offset = -self.settings['sampling', 'decimation'] / self.controller.CLOCK * nsamples / 2
        else:
            offset = 0

        self.controller.acquisition_start()


        self.controller.acq_trigger_source = self.settings['triggering', 'source']

        self.aout.sweep_state = True
        self.aout.enable = True
        self.aout.run()

        QThread.msleep(max((1, int(wait_time * 1000))))
        while not self.controller.acq_trigger_status:
            QThread.msleep(10)
            QtWidgets.QApplication.processEvents()

        while not self.controller.acq_buffer_filled:
            QThread.msleep(10)
            QtWidgets.QApplication.processEvents()

        data_list = [self.controller.analog_in[1].get_data(npts=nsamples)]
        data_list.append(self.controller.analog_in[2].get_data(npts=nsamples))
        axis = Axis('time', units='s', offset=offset,
                    scaling=self.settings['sampling', 'decimation'] / self.controller.CLOCK,
                    size=nsamples)
        self.dte_signal.emit(DataToExport('Redpitaya_dte',
                                          data=[DataFromPlugins(name='RedPitaya', data=data_list,
                                                                dim='Data1D', labels=['AI0'],
                                                                axes=[axis])]))
        self.stop()

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        super().stop()
        self.aout.enable= False
        return ''

if __name__ == '__main__':
    main(__file__)