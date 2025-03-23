#!/usr/bin/env python3

# bittensor import
import bittensor

# standart imports
from collections import namedtuple
import json
import numpy
import os
import time

# Local imports
import subnet_constants


class SubnetDataBase:
    _rizzo_hotkey = "5F2CsUDVbRbVMXTh9fAzF9GacjVX7UapvRxidrxe7z8BYckQ"

    ValidatorData = namedtuple(
        "ValidatorData", [
            "subnet_emission",
            "blocks",
            "block_data",
        ]
    )
    BlockData = namedtuple(
        "BlockData", [
            "rizzo_emission",
            "rizzo_vtrust",
            "avg_vtrust",
            "rizzo_updated",
        ]
    )

    def __init__(self, debug):
        self._debug = debug
        self._validator_data = {}

        # Gather the data for all given subnets
        self._get_subnet_data()

    @property
    def validator_data(self):
        return self._validator_data

    def _print_debug(self, message):
        if self._debug:
            print(message)

    def to_dict(self):
        def serializable(value):
            if isinstance(value, self.BlockData):
                return namedtuple_to_dict(value)
            if isinstance(value, list):
                return [serializable(v) for v in value]
            if isinstance(value, numpy.float32):
                return float(value)
            if isinstance(value, numpy.int64):
                return int(value)
            return value

        def namedtuple_to_dict(data):
            return dict(
                [(f, serializable(getattr(data, f))) for f in data._fields]
            )

        data_dict = {}
        for key in self._validator_data:
            data = self._validator_data[key]
            data_dict[key] = namedtuple_to_dict(data)
        return data_dict

    def _get_subnet_data(self):
        raise NotImplementedError


class SubnetData(SubnetDataBase):
    def __init__(self, netuids, num_intervals, debug):
        self._netuids = netuids
        self._num_intervals = num_intervals

        # Get subtensor and list of netuids.
        self._subtensor = bittensor.subtensor(network="archive")

        super(SubnetData, self).__init__(debug)

    def _get_subnet_data(self):
        self._print_debug("\nGathering data")

        max_attempts = 5
        netuids = self._netuids
        for attempt in range(1, max_attempts+1):
            self._print_debug(f"\nAttempt {attempt} of {max_attempts}")
            for netuid in netuids:
                self._get_validator_data(netuid)

            # Get netuids missing data
            netuids = list(set(netuids).difference(set(self._validator_data)))
            if netuids:
                self._print_debug("\nFailed to gather data for subnets: "
                                 f"{', '.join([str(n) for n in netuids])}.")
            else:
                break

    def _get_validator_data(self, netuid):
        start_time = time.time()
        self._print_debug(f"\nObtaining data for subnet {netuid}\n")

        # Get metagraph for the subnet.
        metagraph = self._subtensor.metagraph(netuid=netuid)

        # Get emission percentage for the subnet.
        subnet_emission = metagraph.emissions.tao_in_emission * 100

        self._validator_data[netuid] = self.ValidatorData(
                subnet_emission=subnet_emission,
                blocks=[],
                block_data=[],
        )

        # Get UID for Rizzo.
        try:
            rizzo_uid = metagraph.hotkeys.index(self._rizzo_hotkey)
        except ValueError:
            rizzo_uid = None
            self._print_debug("WARNING: Rizzo validator not running on subnet "
                 f"{netuid}")
            return

        last_weight_set_block = metagraph.last_update[rizzo_uid]

        for i in range(self._num_intervals):
            try:
                metagraph = self._subtensor.metagraph(
                    netuid=netuid, block=int(last_weight_set_block - 1)
                )
            except:
                print(f"Unable to obtain all {self._num_intervals} weight setting intervals.")
                break

            prev_weight_set_block = metagraph.last_update[rizzo_uid]
            interval = last_weight_set_block - prev_weight_set_block
            rizzo_vtrust = metagraph.Tv[rizzo_uid]
            rizzo_emission = metagraph.E[rizzo_uid]

            # Get all validator uids that have valid stake amount
            all_uids = [
                i for (i, s) in enumerate(metagraph.S)
                if i != rizzo_uid and s > subnet_constants.MIN_STAKE_THRESHOLD
            ]
            # Get all validators that have proper VT and U
            valid_uids = [
                i for i in all_uids
                if (metagraph.Tv[i] > subnet_constants.MIN_VTRUST_THRESHOLD)
                & (last_weight_set_block - metagraph.last_update[i]  < subnet_constants.MAX_U_THRESHOLD)
            ]
            if not valid_uids:
                avg_vtrust = None
            else:
                # Get min/max/average vTrust values.
                # vtrusts = [metagraph.Tv[uid] for uid in valid_uids]
                avg_vtrust = numpy.average(metagraph.Tv[valid_uids])

            block_data = self.BlockData(
                rizzo_emission=rizzo_emission,
                rizzo_vtrust=rizzo_vtrust,
                avg_vtrust=avg_vtrust,
                rizzo_updated=interval,
            )
            self._validator_data[netuid].blocks.append(last_weight_set_block)
            self._validator_data[netuid].block_data.append(block_data)

            last_weight_set_block = prev_weight_set_block

        total_time = time.time() - start_time
        self._print_debug(f"Subnet {netuid} data gathered in "
                         f"{int(total_time)} seconds.")


class SubnetDataFromJson(SubnetDataBase):
    _json_file_name = "validator_data.json"

    def __init__(self, netuid, json_folder):
        self._netuid = netuid
        self._json_folder = json_folder

        # Get subtensor and list of netuids.
        self._subtensor = bittensor.subtensor(network="archive")

        super(SubnetData, self).__init__(False)

    @property
    def json_file(self):
        json_base, json_ext = os.path.splitext(self._json_file_name)
        json_file_name = f"{json_base}.{self._netuid}{json_ext}"
        return os.path.join(self._json_folder, json_file_name)

    def _get_subnet_data(self):
        if not os.path.isfile(self.json_file):
            return

        with open(self.json_file, "r") as fd:
            subnet_data = json.load(fd)
            
        block_data = []
        for subnet_block_data in subnet_data["block_data"]:
            block_data.append(
                self.BlockData(
                    rizzo_emission=subnet_block_data["rizzo_emission"],
                    rizzo_vtrust=subnet_block_data["rizzo_vtrust"],
                    avg_vtrust=subnet_block_data["avg_vtrust"],
                    rizzo_updated=subnet_block_data["rizzo_updated"],
                )
            )
        self._validator_data[self._netuid] = self.ValidatorData(
            subnet_emission=subnet_data["subnet_emission"],
            blocks=subnet_data["blocks"],
            block_data=block_data,
        )
