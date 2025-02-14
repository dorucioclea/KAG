# -*- coding: utf-8 -*-
# Copyright 2023 OpenSPG Authors
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License
# is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.
from abc import ABC, abstractmethod
from typing import List

from kag.builder.component.base import BuilderComponent
from kag.builder.model.chunk import Chunk
from kag.builder.model.sub_graph import SubGraph
from knext.common.base.runnable import Input, Output


class ExtractorABC(BuilderComponent, ABC):
    """
    Interface for extracting sub graph (which contains a list of nodes and a list of edges) from chunks.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def input_types(self):
        return Chunk

    @property
    def output_types(self):
        return SubGraph

    @abstractmethod
    def invoke(self, input: Input, **kwargs) -> List[Output]:
        raise NotImplementedError(
            f"`invoke` is not currently supported for {self.__class__.__name__}."
        )
