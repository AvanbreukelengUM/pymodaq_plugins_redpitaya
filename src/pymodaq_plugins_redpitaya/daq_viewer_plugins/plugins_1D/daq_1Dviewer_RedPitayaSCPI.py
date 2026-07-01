import numpy as np
from qtpy import QtWidgets
from qtpy.QtCore import QThread
from pymodaq.utils.daq_utils import ThreadCommand
from pymodaq.utils.data import DataFromPlugins, Axis, DataToExport
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.parameter import Parameter
from pymodaq_plugins_redpitaya.utils import Config

from pymeasure.instruments.redpitaya.redpitaya_scpi import RedPitayaScpi, AnalogInputFastChannel

class DAQ_1DViewer_RedPitayaSCPI(DAQ_Viewer_base):
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

        {'title': 'Sampling:', 'name': 'sampling', 'type': 'group', 'children': [
            {'title': 'Decimation:', 'name': 'decimation', 'type': 'int', 'step': 2, 'max': 2**16,
             'value': plugin_config('sampling', 'decimation')},
            {'title': 'Average skipped samples:', 'name': 'average', 'type': 'bool', 'value': False},
            {'title': 'Sample rate:', 'name': 'sample_rate', 'type': 'int', 'readonly': True},
            {'title': 'Nsamples:', 'name': 'nsamples', 'type': 'int',
             'value': plugin_config('sampling', 'nsamples')},
            {'title': 'Buffer Length:', 'name': 'buffer_length', 'type': 'int', 'readonly': True},
            {'title': 'Window Length:', 'name': 'window_length', 'type': 'float',
             'value': 0, 'siPrefix': True, 'suffix': 's', 'readonly': True},
            {'title': 'Gain1 (jumper CH1):', 'name': 'gain1', 'type': 'list',
             'limits': AnalogInputFastChannel.GAINS, 'value': plugin_config('sampling', 'gain1')},
            {'title': 'Gain2 (jumper CH2):', 'name': 'gain2', 'type': 'list',
             'limits': AnalogInputFastChannel.GAINS, 'value': plugin_config('sampling', 'gain2')},

        ]},
        {'title': 'Triggering:', 'name': 'triggering', 'type': 'group', 'children': [
            {'title': 'Source:', 'name': 'trigger_source', 'type': 'list',
             'limits': RedPitayaScpi.TRIGGER_SOURCES, 'value': plugin_config('trigger', 'source')},
            {'title': 'Level (V):', 'name': 'level', 'type': 'float',
             'value': plugin_config('trigger', 'level')},
            {'title': 'Center Trigger:', 'name': 'center_trigger', 'type': 'bool',
             'value': plugin_config('trigger', 'center_trigger')},
        ]},
        ]

    def ini_attributes(self):
        self.controller: RedPitayaScpi = None
        self.x_axis: Axis = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == 'decimation':
            self.controller.decimation = param.value()
            self.settings.child('sampling', 'decimation').setValue(self.controller.decimation)
            self.settings.child('sampling', 'sample_rate').setValue(self.controller.CLOCK /
                                                        self.controller.decimation)
            self.update_window_length()

        elif param.name() == 'level':
            self.controller.acq_trigger_level = param.value()

        elif param.name() == 'center_trigger':
            self._center_trigger()
            pass

        elif param.name() == 'average':
            self.controller.average_skipped_samples = param.value()

        elif param.name() == 'nsamples':
            self._center_trigger()
            self.update_window_length()

        elif param.name() == 'trigger_source':
            self.controller.acq_trigger_source = param.value()

        elif param.name() == 'gain1':
            # self.controller.acq_gain1 = param.value()
            self.ain(channel = 1).gain = param.value()
        elif param.name() == 'gain2':
            # self.controller.acq_gain2 = param.value()
            self.ain(channel = 2).gain = param.value()

    def _center_trigger(self):
        if self.settings['triggering', 'center_trigger']:
            self.controller.acq_trigger_delay_samples = \
                int(self.settings['sampling', 'buffer_length'] / 2 -
                    self.settings['sampling', 'nsamples'] / 2)
        else:
            self.controller.acq_trigger_delay_samples = int(self.settings['sampling',
            'buffer_length'] / 2)

    def update_window_length(self):
        self.settings.child('sampling', 'window_length').setValue(
            self.settings['sampling', 'nsamples'] / self.settings['sampling', 'sample_rate'])

    def ain(self,channel = 1):
        """ It defines what output channel the user chose"""
        return self.controller.analog_in[channel]

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
                               new_controller=RedPitayaScpi(ip_address=self.settings['ip_address'],
                                                            port=self.settings['port']))
        bname = self.controller.name
        self.settings.child('bname').setValue(bname)

        self.controller.acquisition_reset()

        self.controller.acq_format = 'ASCII'
        self.controller.acq_units = 'VOLTS'

        self.ain(channel=1).gain = self.settings['sampling', 'gain1']
        self.ain(channel=2).gain = self.settings['sampling', 'gain2']

        # self.controller.acq_gain1 = self.settings['sampling', 'gain1']
        # self.controller.acq_gain2 = self.settings['sampling', 'gain2']

        self.controller.acq_trigger_level = self.settings['triggering', 'level']

        self.controller.decimation = self.settings['sampling', 'decimation']
        self.controller.decimation = self.settings['sampling', 'decimation']
        self.controller.average_skipped_samples = self.settings['sampling', 'average']
        self.settings.child('sampling', 'buffer_length').setValue(self.controller.buffer_length)
        self.settings.child('sampling',
                            'nsamples').setLimits((1, self.settings['sampling', 'buffer_length']))
        self.settings.child('sampling', 'sample_rate').setValue(self.controller.CLOCK /
                                                    self.controller.decimation)
        self._center_trigger()

        info = f"Succesfully connected to the Redpitaya {bname} board"
        initialized = True
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        pass

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

        nsamples = self.settings['sampling', 'nsamples']
        wait_time = nsamples / self.controller.CLOCK * self.settings['sampling', 'decimation']
        scaling = self.settings['sampling', 'decimation'] / self.controller.CLOCK
        if self.settings['triggering',  'center_trigger']:
            offset_axis = -scaling * nsamples / 2
            offset = nsamples / 2
        else:
            offset_axis = 0
            offset = 0

        self.controller.acquisition_start()
        # QThread.msleep(max((1, int(wait_time * 1000))))
        self.controller.acq_trigger_source = self.settings['triggering', 'trigger_source'] #doesn't make much sense to have it here but doesn't work if removed...

        while not self.controller.acq_trigger_status:
            QThread.msleep(10)
            QtWidgets.QApplication.processEvents()

        while not self.controller.acq_buffer_filled:
            QThread.msleep(10)
            QtWidgets.QApplication.processEvents()

        # t00 = time.time()
        # while True:
        #     print(time.time()-t00)
        #     t00 = time.time()
        #     # trig_position = self.controller.acq_trigger_position
        #     # data_list = [self.controller.analog_in[1].get_data_from(trig_position - offset, nsamples)]

        trig_position = self.controller.acq_trigger_position

        data_list = [self.controller.analog_in[1].get_data_from(trig_position-offset, nsamples)]
        data_list.append(self.controller.analog_in[2].get_data_from(trig_position-offset, nsamples))
        axis = Axis('time', units='s', offset=offset_axis,
                    scaling=scaling,
                    size=nsamples)
        self.dte_signal.emit(DataToExport('Redpitaya_dte',
                                          data=[DataFromPlugins(name='RedPitaya', data=data_list,
                                                                dim='Data1D', labels=['IN1', 'IN2'],
                                                                axes=[axis])]))

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        self.controller.acquisition_stop()
        return ''


if __name__ == '__main__':
    main(__file__, init=False)
