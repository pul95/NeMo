# Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from enum import Enum
from typing import Dict, Optional

import torch

from nemo.core.neural_types import AxisKind, NeuralType

__all__ = ['ExportFormat', 'Exportable']


class ExportFormat(Enum):
    """Which format to use when exporting a Neural Module for deployment"""

    ONNX = 0


class Exportable(ABC):
    """
    This Interface should be implemented by particular classes derived from nemo.core.NeuralModule or nemo.core.ModelPT.
    It gives these entities ability to be exported for deployment to formats such as ONNX.
    """

    def export(
        self,
        output: str,
        input_example=None,
        output_example=None,
        format: ExportFormat = ExportFormat.ONNX,
        onnx_opset_version=11,
    ):
        _in_example, _out_example = self.prepare_for_export()
        if input_example is not None:
            _in_example = input_example
        if output_example is not None:
            _out_example = output_example

        # Check if output already exists
        if os.path.exists(output):
            raise FileExistsError(f"Destination {output} already exists. " f"Aborting export.")

        if not (hasattr(self, 'input_types') and hasattr(self, 'output_types')):
            raise NotImplementedError('For export to work you must define input and output types')
        input_names = list(self.input_types.keys())
        output_names = list(self.output_types.keys())
        dynamic_axes = defaultdict(list)

        # extract dynamic axes and remove unnecessary inputs/outputs
        # for input_ports
        for _name, ntype in self.input_types.items():
            if _name in self.disabled_deployment_input_names:
                input_names.remove(_name)
                continue
            self.__extract_dynamic_axes(_name, ntype, dynamic_axes)
        # for output_ports
        for _name, ntype in self.output_types.items():
            if _name in self.disabled_deployment_output_names:
                output_names.remove(_name)
                continue
            self.__extract_dynamic_axes(_name, ntype, dynamic_axes)

        if len(dynamic_axes) == 0:
            dynamic_axes = None

        # Set module to eval mode
        self.eval()

        # Attempt export
        if format == ExportFormat.ONNX:
            if _in_example is None:
                raise ValueError(f'Example input is None, but ONNX tracing was attempted')
            if _out_example is None:
                if isinstance(_in_example, tuple):
                    _out_example = self.forward(*_in_example)
                else:
                    _out_example = self.forward(_in_example)
            with torch.jit.optimized_execution(True):
                jitted_model = torch.jit.trace(self, _in_example)

            torch.onnx.export(
                jitted_model,
                _in_example,
                output,
                input_names=input_names,
                output_names=output_names,
                verbose=False,
                export_params=True,
                do_constant_folding=True,
                dynamic_axes=dynamic_axes,
                opset_version=onnx_opset_version,
                example_outputs=_out_example,
            )
        else:
            raise ValueError(f'Encountered unknown export format {format}.')

    @property
    def disabled_deployment_input_names(self):
        """Implement this method to return a set of input names disabled for export"""
        return set()

    @property
    def disabled_deployment_output_names(self):
        """Implement this method to return a set of output names disabled for export"""
        return set()

    @staticmethod
    def __extract_dynamic_axes(port_name, ntype: NeuralType, dynamic_axes: defaultdict):
        if ntype.axes:
            for ind, axis in enumerate(ntype.axes):
                if axis.kind == AxisKind.Batch or axis.kind == AxisKind.Time:
                    dynamic_axes[port_name].append(ind)

    def prepare_for_export(self) -> (Optional[torch.Tensor], Optional[torch.Tensor]):
        """
        Implement this method to prepare module for export. Do all necessary changes on module pre-export here.
        Also, return a pair in input, output examples for tracing.
        Returns:
            A pair of (input, output) examples.
        """
        pass
        # return (None, None)
