import numpy as np

from pymodaq.extensions.data_mixer.model import DataMixerModel, np  # np will be used in method eval of the formula

from pymodaq_utils.math_utils import find_index


from pymodaq_data.data import DataToExport, DataWithAxes, DataCalculated, DataDim, Axis
from pymodaq_gui.parameter import Parameter

from pymodaq.extensions.data_mixer.parser import (
    extract_data_names, split_formulae, replace_names_in_formula)


class SweepFFT(DataMixerModel):
    params = [
        {'title': 'Get Data:', 'name': 'get_data', 'type': 'bool_push', 'value': False,
         'label': 'Get Data'},
        {'title': 'Data1D:', 'name': 'data1D', 'type': 'itemselect',
         'value': dict(all_items=[], selected=[])},
    ]

    def ini_model(self):
        self.show_data_list()

    def show_data_list(self):
        dte = self.modules_manager.get_det_data_list()
        data_list1D = dte.get_full_names('data1D')
        self.settings.child('data1D').setValue(dict(all_items=data_list1D, selected=[]))

    def update_settings(self, param: Parameter):
        if param.name() == 'get_data':
            self.show_data_list()

    def process_dte(self, dte: DataToExport):
        dte_processed = DataToExport('computed')
        if len(self.settings['data1D']['selected']) !=  0:

            dwa_extracted = dte.get_data_from_full_name(self.settings['data1D']['selected'][0])

            dwa_ft = dwa_extracted.ft(0, axis_label='Frequency', axis_units='Hz')
            dwa_ft.get_axis_from_index(0)[0].data *= 1/(2*np.pi)

            frequency = dwa_ft.axes[0].get_data()

            intensity = dwa_ft.abs()[1]

            ind_0 = find_index(frequency, 100)[0][0]
            ind_end = find_index(frequency, 25000)[0][0]

            ind_max = np.argmax(intensity[ind_0:ind_end])


            intensity = intensity[ind_0:ind_end]
            frequency = frequency[ind_0: ind_end]
            phase = np.unwrap(np.angle(dwa_ft[1][ind_0:ind_end])-np.angle(dwa_ft[0][ind_0:ind_end]))
            phase -= phase[ind_max]

            dte_processed.append(DataCalculated('Intensity',
                                                data=[intensity],
                                                labels=['Intensity'],
                                                axes=[Axis('Frequency', units='Hz', data=frequency)]),
                                 DataCalculated('Phase',
                                                data=[phase],
                                                labels=['Phase'],
                                                axes=[Axis('Frequency', units='Hz', data=frequency)]))


        return dte_processed




