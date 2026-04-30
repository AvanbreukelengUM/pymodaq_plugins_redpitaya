
from typing import Union, List, Dict
from pymodaq.control_modules.move_utility_classes import (DAQ_Move_base, comon_parameters_fun,
                                                          main, DataActuatorType, DataActuator)

from pymodaq_utils.utils import ThreadCommand  # object used to send info back to the main thread

from pymodaq_gui.parameter import Parameter

from pymeasure.instruments.redpitaya.redpitaya_scpi import RedPitayaScpi, AnalogOutputFastChannel

from pymodaq_data import Q_

from pymodaq_plugins_redpitaya.utils import Config

plugin_config = Config()

class DAQ_Move_RedpitayaSCPI(DAQ_Move_base):
    """ Instrument plugin class for Red Pitaya

       This object inherits all functionalities to communicate with PyMoDAQ’s DAQ_Move module through
       inheritance via DAQ_Move_base. It makes a bridge between the DAQ_Move module and the
       Python wrapper of a particular instrument.

       * Should be compatible with all redpitaya flavours using the SCPI communication protocol
       * Tested with Red Pitaya 2.00-37 OS | STEMlab 125-14 Pro (Gen 2) version
       * PyMoDAQ >= 5.0.5
       * Tested with Linux Ubuntu 24.04.1 LTS
       * Installation instruction:
        These instructions are valid when using an Ethernet cable to communicate with the Red Pitaya.
        The instrument is accessed using a TCP/IP Socket communication adapter, in the form: “TCPIP::x.y.z.k::port::SOCKET”
        - x.y.z.k is the IP address of the SCPI server (that should be activated on the board)
        - port is the TCP/IP port number, usually 5000
        To activate the use of the Red Pitaya:
        1. Connect the redpitaya to your computer/network with an ethernet cable.
        2. Enter the url address written on the network plug (on the Red Pitaya)
           It should be something like “RP-F0B462.LOCAL/”
        3. Browse the menu, open the System application then the Network manager application
           Look at the ip_address, and modify the config_template
        4. Return to the menu, open the Development application and activate the SCPI server.
        5. You can now run daq_move_RedpiatayaSCPI.py

    Attributes:
    -----------
    controller: object
        The particular object that allow the communication with the hardware, in general a python wrapper around the
         hardware library.
       """

    is_multiaxes = True
    _axis_names: Union[List[str], Dict[str, int]] = ['amplitude', 'frequency']
    _controller_units: Union[str, List[str]] = ['V','Hz']
    _epsilon: Union[float, List[float]] = [0.005,1] # Detailing 5mV and 1Hz. Resolution of reading is 5mV
    # _epsilon: Union[float, List[float]] = 0.1  # Detailing 1mV and 1Hz #TODO replace this by a value that is correct depending on your controller
    # TODO it could be a single float of a list of float (as much as the number of axes)
    data_actuator_type = DataActuatorType.DataActuator

    params = [   {'title': 'IP Address:', 'name': 'ip_address', 'type': 'str',
                  'value': plugin_config('ip_address')},
                 {'title': 'Port:', 'name': 'port', 'type': 'int', 'value': plugin_config('port')},
                 {'title': 'Board name:', 'name': 'bname', 'type': 'str', 'readonly': True},

                 {'title': 'Channel', 'name': 'channel', 'type': 'list', 'limits':{'1': 1, '2': 2},
                  'value': plugin_config('generator', 'channel')},

                 {'title': 'Gen Trigger:', 'name': 'gen_trigger', 'type': 'list',
                  'limits': AnalogOutputFastChannel.GEN_TRIGGER_SOURCES, 'value': plugin_config('generator', 'gen_trigger'),
                  'readonly': True},  #[Type]: "not working at the moment"},
                 {'title': 'Enable', 'name': 'enable', 'type': 'bool', 'value': False },
                {'title': 'Shape', 'name': 'shape', 'type': 'list',
                      'limits': AnalogOutputFastChannel.SHAPES, 'value': plugin_config('generator', 'shape')},
                 {'title': 'Offset', 'name': 'offset', 'type': 'float', 'limits' : AnalogOutputFastChannel.OFFSETS,
                  'value': plugin_config('generator', 'offset')},
                {'title': 'Phase', 'name': 'phase', 'type': 'float', 'limits' : AnalogOutputFastChannel.PHASES,
                      'value': plugin_config('generator', 'phase')},
                {'title': 'Dutycycle', 'name': 'dutycycle', 'type': 'float', 'limits' : AnalogOutputFastChannel.CYCLES,
                      'value': plugin_config('generator', 'cycle')},

                 {'title': 'Sweep', 'name': 'sweep_group', 'type': 'group', 'children': [
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
                ] + comon_parameters_fun(is_multiaxes, axis_names=_axis_names, epsilon=_epsilon)
    # _epsilon is the initial default value for the epsilon parameter allowing pymodaq to know if the controller reached
    # the target value. It is the developer responsibility to put here a meaningful value

    def ini_attributes(self):
        self.controller: RedPitayaScpi = None
        pass

    def get_actuator_value(self):
        """Get the current value from the hardware with scaling conversion.

        Returns
        -------
        float: The position obtained after scaling conversion.
        """
        pos = DataActuator(data=getattr(self.aout, self.axis_name),
                           units=self.axis_unit)
        pos = self.get_position_with_scaling(pos)

        return pos

    def close(self):
        """Terminate the communication protocol"""
        self.aout.enable = False

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == 'axis':
            if param.value() =='frequency':
                self.settings.child('bounds', 'min_bound').setValue(1e-6)
                self.settings.child('bounds', 'max_bound').setValue(50e6)
            elif param.value == 'amplitude':
                self.settings.child('bounds', 'min_bound').setValue(0)
                self.settings.child('bounds', 'max_bound').setValue(2)

            self.settings.child('bounds', 'is_bounds').value()
            self.settings.child('bounds', 'is_bounds').setValue(True)
        elif param.name() == 'enable':
            self.aout.enable = param.value()
        elif param.name() == 'shape':
            self.aout.shape = param.value()
        elif param.name() == 'offset':
            self.aout.offset = param.value()
        elif param.name() == 'phase':
            self.aout.phase = param.value()
        elif param.name() == 'dutycycle':
            self.aout.dutycycle = param.value()
        elif param.name() == 'sweep_mode':
            self.aout.sweep_mode = param.value()
        elif param.name() == 'sweep_start_frequency':
            self.aout.sweep_start_frequency = param.value()
        elif param.name() == 'sweep_stop_frequency':
            self.aout.sweep_stop_frequency = param.value()
        elif param.name() == 'sweep_time':
            self.aout.sweep_time = int(param.value())
        elif param.name() == 'sweep_state':
            self.aout.sweep_state = param.value()
        elif param.name() == 'sweep_direction':
            self.aout.sweep_direction = param.value()
        elif param.name() == 'gen_trigger':
            self.aout.gen_trigger_source = param.value()
            # TODO implement trigger source setting correctly

    def is_enabled(self) -> bool:
        "It defines if the supply voltage is enabled on the output channel chosen"
        return self.settings['enable'] == True

    @property
    def aout(self):
        """ It defines what output channel the user chose"""
        return self.controller.analog_out[self.settings['channel']]

    def ini_stage(self, controller=None):
        """Actuator communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator by controller (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """

        if self.is_master:  # is needed when controller is master
            self.controller = RedPitayaScpi(ip_address=self.settings['ip_address']) #  arguments for instantiation!)
            # self.controller = RedPitayaScpi(ip_address=plugin_config('ip_address')) #  arguments for instantiation!)
        else:
            self.controller = controller

        self.aout.shape = self.settings['shape'] #plugin_config('generator', 'shape')

        self.settings.child('bounds', 'is_bounds').setOpts(readonly=True)

        self.aout.enable = True
        self.aout.run() # TODO change this function to work with other trigger sources than INTernal trigger

        info = "Whatever info you want to log"
        initialized = True
        return info, initialized

    def move_abs(self, value: DataActuator):
        """ Move the actuator to the absolute target defined by value

        Parameters
        ----------
        value: (float) value of the absolute target positioning
        """
        if not self.is_enabled():
            self.aout.enable = True
        value = self.check_bound(value)  #if user checked bounds, the defined bounds are applied here
        self.target_value = value
        value = self.set_position_with_scaling(value)  # apply scaling if the user specified one
        print("axis name: ",self.axis_name)
        print("axis value: ",value)
        setattr(self.aout, self.axis_name, value.value(self.axis_unit))
        self.aout.run() # regenerates trigger, otherwise it will continue to generate on the passed settings
        #  TODO change this function to work with other trigger sources than INTernal trigger

    def move_rel(self, value: DataActuator):
        """ Move the actuator to the relative target actuator value defined by value

        Parameters
        ----------
        value: (float) value of the relative target positioning
        """
        value = self.check_bound(self.current_position + value) - self.current_position
        self.target_value = value + self.current_position
        self.move_abs(self.target_value)

    def move_home(self):
        """Call the reference method of the controller"""
        pass

    def stop_motion(self):
        """Stop the actuator and emits move_done signal"""
        pass


if __name__ == '__main__':
    main(__file__, init=False)
