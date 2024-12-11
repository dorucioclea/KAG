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

import os
from kag.common.registry import Registrable
from kag.common.utils import reset, bold, red


class CheckPointer(Registrable):
    """
    A class for managing checkpoints in a distributed environment.

    This class provides methods to open, read, write, and close checkpoint files.
    It is designed to handle checkpoints in a distributed setting, where multiple
    processes may be writing checkpoints in parallel.

    Attributes:
        ckpt_file_name (str): The format string for checkpoint file names.
    """

    ckpt_file_name = "kag_checkpoint_{}_{}.ckpt"

    def __init__(self, ckpt_dir: str, rank: int = 0, world_size: int = 1):
        """
        Initializes the CheckPointer with the given checkpoint directory, rank, and world size.

        Args:
            ckpt_dir (str): The directory where checkpoint files are stored.
            rank (int): The rank of the current process (default is 0).
            world_size (int): The total number of processes in the distributed environment (default is 1).
        """
        self._ckpt_dir = ckpt_dir
        if not os.path.exists(ckpt_dir):
            os.makedirs(ckpt_dir, exist_ok=True)
        self.rank = rank
        self.world_size = world_size
        self._ckpt_file_path = os.path.join(
            self._ckpt_dir, CheckPointer.ckpt_file_name.format(rank, world_size)
        )
        self._ckpt = self.open()
        if len(self._ckpt) > 0:
            print(
                f"{bold}{red}Existing checkpoint found in {self._ckpt_dir}{reset}, with {len(self._ckpt)} processed records."
            )

    def open(self):
        """
        Opens the checkpoint file and returns the checkpoint object.

        Returns:
            Any: The checkpoint object, which can be used for reading and writing.
        """
        raise NotImplementedError("open not implemented yet.")

    def read_from_ckpt(self, key):
        """
        Reads a value from the checkpoint file using the specified key.

        Args:
            key (str): The key to retrieve the value from the checkpoint.

        Returns:
            Any: The value associated with the key in the checkpoint.
        """
        raise NotImplementedError("read_from_ckpt not implemented yet.")

    def write_to_ckpt(self, key, value):
        """
        Writes a value to the checkpoint file using the specified key.

        Args:
            key (str): The key to store the value in the checkpoint.
            value (Any): The value to be stored in the checkpoint.
        """
        raise NotImplementedError("write_to_ckpt not implemented yet.")

    def close(self):
        """
        Closes the checkpoint file.
        """
        raise NotImplementedError("close not implemented yet.")

    def exists(self, key):
        """
        Checks if a key exists in the checkpoint file.

        Args:
            key (str): The key to check for existence in the checkpoint.

        Returns:
            bool: True if the key exists in the checkpoint, False otherwise.
        """
        raise NotImplementedError("close not implemented yet.")
